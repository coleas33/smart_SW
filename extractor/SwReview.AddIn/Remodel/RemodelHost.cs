using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using SwReview.AddIn.Review;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel;

/// <summary>Everything <see cref="RemodelHost"/> is given; injected so it is testable headless.</summary>
public sealed class RemodelHostOptions
{
    /// <param name="channel">Where replies and unsolicited messages go.</param>
    /// <param name="runRoot">The run root in force, read fresh: the restart a settings save makes moves it.</param>
    public RemodelHostOptions(IPageChannel channel, Func<string> runRoot)
    {
        Channel = channel ?? throw new ArgumentNullException(nameof(channel));
        RunRoot = runRoot ?? throw new ArgumentNullException(nameof(runRoot));
        RunRootsInForce = () => new[] { RunRoot() };
        RunRootForANewRun = () => RunRoot();
    }

    public IPageChannel Channel { get; }

    public Func<string> RunRoot { get; }

    /// <summary>
    /// Every run root that has been in force in this SOLIDWORKS session, the one in force among them (owner
    /// decision 154A, the reviews' finding F6): a run made under any of them is this pane's to open - its report
    /// and its folder - after a settings save has moved the run root. The run root in force alone by default.
    /// </summary>
    public Func<IReadOnlyList<string>> RunRootsInForce { get; set; }

    /// <summary>
    /// The run root a plan's folder is made under, and a Start's plan must lie under, read once each pass of the
    /// gate (owner decision 154A, with 153A's record of the settings in force): the run root in force, or null while
    /// a start of the backend under way would bring another into force, which a plan and a Start refuse. The run
    /// root in force by default.
    /// </summary>
    public Func<string?> RunRootForANewRun { get; set; }

    /// <summary>
    /// The run root saved in the Review tab's Settings, which the next restart brings into force, or null when no
    /// review host knows it (the reviews of 154A's merge, N4): a start refused for the run root in force while
    /// another is saved says to retry the restart, not to choose a folder again. None by default.
    /// </summary>
    public Func<string?> RunRootSaved { get; set; } = () => null;

    /// <summary>The backend's endpoint, or null before it is listening.</summary>
    public Func<BackendEndpoint?> Backend { get; set; } = () => null;

    /// <summary>A failed start with no backend up, remembered by the Review host (owner decision 160A).</summary>
    public Func<bool> BackendStartFailed { get; set; } = () => false;

    /// <summary>The open document, asked for fresh each time; SOLIDWORKS owns the answer.</summary>
    public Func<PageDocument?> CurrentDocument { get; set; } = () => null;

    /// <summary>
    /// The copy, the dump, the planner and the executor. Null until the add-in is attached to a
    /// SOLIDWORKS session, which is a state the pane really has.
    /// </summary>
    public IRemodelPipeline? Pipeline { get; set; }

    /// <summary>
    /// Whether the attached bridge can execute remodel commands. The add-in reads this from
    /// the tool service; tests and future seat-backed hosts can provide their own capability.
    /// Unknown leaves the bridge unavailable check to the pipeline, while Unavailable is
    /// refused before any bridge call is made.
    /// </summary>
    public Func<RemodelAvailability> RemodelAvailability { get; set; } =
        () => global::SwReview.AddIn.Remodel.RemodelAvailability.Available;

    /// <summary>
    /// Which tool-service attachment is listening now, or null while none is (decision 22A,
    /// 004 T160).
    ///
    /// The add-in answers with <see cref="ToolService.ToolServiceGate.Attachment"/>: the pipe
    /// name of the running service, which is minted fresh for every start, so it names exactly
    /// one bridge dispatcher - and the one remodel session that dispatcher can hold. A plan
    /// records it, and `remodel.start` refuses a run whose attachment is not the one listening
    /// now, because a re-attach throws that session away.
    ///
    /// Null by default, and null never matches: a host nobody told about the tool service
    /// refuses every Start as `SessionLost` rather than start a run on a session it cannot
    /// vouch for.
    /// </summary>
    public Func<string?> ToolServiceAttachment { get; set; } = () => null;

    /// <summary>
    /// Makes the run's folder the pane's latest run, the same way a Model check's folder does
    /// (<see cref="Model.ModelCheckHostOptions.RegisterLatestRun"/>). There is one answer to
    /// "which folder is the pane looking at" and it is not this host's to keep: `entity.show`
    /// resolves ids through the package in that folder and the Ask tab opens in it.
    /// </summary>
    public Action<string> RegisterLatestRun { get; set; } = _ => { };

    /// <summary>Show in SOLIDWORKS; null before the add-in is attached.</summary>
    public Func<IEntityResolver?> EntityResolver { get; set; } = () => null;

    /// <summary>What `report.open`, `folder.open` and `log.open` shell out through.</summary>
    public Func<IPathOpener> Opener { get; set; } = () => new ShellPathOpener();

    /// <summary>%LOCALAPPDATA%\SwReview\logs by default; what `log.open` opens.</summary>
    public Func<string> LogFolder { get; set; } = ReviewHostOptions.DefaultLogFolder;

    /// <summary>Run-folder timestamps. Injected so the naming rule is testable.</summary>
    public Func<DateTime> Now { get; set; } = () => DateTime.Now;

    /// <summary>Values that must never reach the page (FR-015).</summary>
    public Func<IEnumerable<string?>> Secrets { get; set; } = () => new string?[0];

    /// <summary>What the executor is bounded by. Reported to the page, never set by it.</summary>
    public RemodelLimits Limits { get; set; } = RemodelLimits.Default;

    /// <summary>
    /// Where phases B to D actually execute.
    ///
    /// Off the message thread by default, and that is not an optimisation: a run can take
    /// twenty minutes, and `remodel.stop` is delivered on the message thread. A run that
    /// occupied that thread would be a run that cannot be stopped. Tests substitute an inline
    /// scheduler so the message order they read is the order the page would see.
    /// </summary>
    public Action<Action> Schedule { get; set; } = work => Task.Run(work);

    /// <summary>
    /// Owner decision 145A: begins a plan or a run - what <see cref="RemodelHost.RunInProgress"/>
    /// covers - as a turn begins, so a settings restart and a remodel run never overlap. Called
    /// with the step that marks the host busy, after every refusal that needs no call: a settings
    /// restart that waits is made first, or the one being made is waited for, then the step is run
    /// under the restart's own lock and null answered; or the step is not run and the refusal is
    /// answered - what holds the restart back, or the restart's failure - with its class, words and
    /// flag. The add-in answers it through the review host (`ReviewHost.BeginRemodelRun`), which
    /// keeps the restart on another pump. By default there is no restart to wait for, and the
    /// step runs at once.
    /// </summary>
    public Func<Action, BackendRequestException?> BeginRun { get; set; } = begin =>
    {
        begin();
        return null;
    };

    /// <summary>
    /// Whether a settings restart stands before a plan or a run - one waits to be made, or one is
    /// being made - which the gate (<see cref="BeginRun"/>) makes, or waits for, first (owner
    /// decision 145A, found on review). Read only to tell the page so; the gate decides. The add-in
    /// answers it through the review host (`ReviewHost.RestartAhead`). By default none does.
    /// </summary>
    public Func<bool> RestartAhead { get; set; } = () => false;

    /// <summary>
    /// Owner decision 152A, on the Codex review (X2): holds the tool service's attachment for a plan or
    /// a run, taken once the host is busy and before the attachment is read, and let go when the host
    /// is free again - so no follow of the active document takes the bridge down under them, even one
    /// whose busy question was out as they began - or null when no service is listening to hold, which
    /// refuses the press. The add-in answers it through the gate (<c>ToolServiceGate.HoldAttachment</c>).
    /// By default there is no gate, and nothing is held.
    /// </summary>
    public Func<IDisposable?> HoldToolService { get; set; } = () => ToolServiceHold.Nothing;

    /// <summary>
    /// What the run root rule reads of Windows (owner decision 154A): a share, a mapped or substituted drive,
    /// a link. Windows itself by default; injected so a test fakes each without making one.
    /// </summary>
    public IRunRootProbe RunRootProbe { get; set; } = Native.WindowsRunRootProbe.Instance;

    /// <summary>
    /// Owner decision 159A (004 research R19): where the host writes, for whoever debugs, what a failure said
    /// where the tab told it in its own words - a refusal's class and sentence, an exception's whole text -
    /// masked as everything the host sends is (FR-015). The add-in writes it to its own log (`addin.log`, in
    /// the folder the tab's View log opens); nowhere by default, so no test writes into the engineer's log.
    /// </summary>
    public Action<string> Log { get; set; } = _ => { };
}

/// <summary>
/// The Remodel page's other half: `ready`, every `remodel.*` row of
/// `specs/004-resilient-remodeler/contracts/pane-remodel-messages.md`, and the four rows every
/// pane host shares, delegated to feature 003's <see cref="PaneActions"/>.
///
/// What it does not do is, again, most of the design:
///
/// <b>It decides nothing about the model.</b> What should move, where it should go, whether a
/// group is contiguous, what cannot be fixed and whether the geometry is unchanged are Python
/// pure functions; what SOLIDWORKS is asked to do is <see cref="IRemodelPipeline"/>. This class
/// owns the order of the messages and the refusals, and that is all it owns.
///
/// <b>It never takes a handle to the source.</b> The source's path leaves this class once, in
/// a <see cref="RemodelCopyRequest"/>, as the source of a filesystem copy. Every other call
/// addresses the run folder. The source is unreachable rather than merely un-targeted, which
/// is the property the constitution's re-modeler exception rests on.
///
/// <b>It does not remember the run's state.</b> `plan.json` carries it, and `remodel.result`
/// and `remodel.start` both read it from there, so a run interrupted by a crash still answers
/// and is still refused a resume (data-model.md section 11).
///
/// <b>It takes no path from the page.</b> `run_dir` is echoed back from a `remodel.planned`
/// this host issued and is resolved against this host's own run record; anything else is
/// `RunNotFound`, before any filesystem call is made with it.
///
/// One run per host, and the page is told so by name: a second `remodel.plan` or
/// `remodel.start` while one is in flight is `error {error_class: "RunInProgress"}`, the same
/// shape `settings.save` already uses for `TurnRunning` (RK-10).
///
/// Threading: <see cref="Receive"/> is not re-entrant and is delivered one message at a time,
/// off the SOLIDWORKS UI thread. The run itself executes on
/// <see cref="RemodelHostOptions.Schedule"/> so that `remodel.stop` can be delivered while it
/// is running; the only state the two share is the run's stop flag, written atomically, and -
/// owner decision 155A - the run's end: the host freed from it, and what its ending holds back
/// meanwhile, under one lock, which `init`'s reading of a run in flight takes too, and - owner
/// decision 159A - a stop's decision and the Stops waiting for the run's end.
/// </summary>
public sealed class RemodelHost : IDisposable
{
    /// <summary>
    /// What the tab says when this build has no in-process remodel seat: the capability, in
    /// the engineer's words, and what it means for the part on screen (U13,
    /// docs/history/pane-findings-2026-09-20-review-gui.md section 6). It names no command. The
    /// standalone probe is a testing procedure with no document open, and it lives in the
    /// workstation handover, not in a Task Pane read by someone with a part open.
    /// </summary>
    public const string NoSeatMessage =
        "Remodel is not in this build yet. This tab will not change the open part.";

    /// <summary>What a forged request reads while the service is still attaching.</summary>
    public const string SeatCheckingMessage =
        "remodel seat availability is still being checked; wait for the tool service to attach.";

    /// <summary>
    /// What `remodel.start` answers a plan whose tool-service attachment is gone (decision 22A,
    /// `contracts/pane-remodel-messages.md`): the add-in reconnected to SOLIDWORKS after the
    /// plan was made, and the bridge session holding the copy did not carry over.
    ///
    /// In the engineer's words, like <see cref="NoSeatMessage"/>: no command, none of the
    /// build's plumbing, and no path - the source's least of all, since nothing after the copy
    /// may name it. It reassures only about the engineer's original part, and names the button
    /// that is the way back by the label the page gives it.
    /// </summary>
    public const string SessionLostMessage =
        "This plan can no longer be started. The add-in reconnected to SOLIDWORKS after the plan "
        + "was made, which happens when the active document changes, and the plan did not carry "
        + "over to the new connection. " + PartNotChanged + " Make your part the active "
        + "document and press Remodel a copy to plan again.";

    /// <summary>
    /// What `remodel.plan_lost` tells the page as soon as the plan on screen can no longer be
    /// started (decision 24A, `contracts/pane-remodel-messages.md`): SOLIDWORKS switched
    /// documents, the tool service re-attached, and the bridge session holding the plan's copy
    /// went with the old attachment. <see cref="SessionLostMessage"/> stays Start's answer to
    /// the same condition, for a Start that reaches the host before this reaches the page.
    ///
    /// In the same plain words, by the same rule: no command, no path, none of the build's
    /// plumbing. It names the button the page offers beside it by the label the page gives it.
    /// The Remodel page reads no words file, so this constant is its words source, printed
    /// verbatim.
    /// </summary>
    public const string PlanLostMessage =
        "This plan was made before SOLIDWORKS switched documents, so it can no longer be "
        + "started. " + PartNotChanged + " Make your part the active document and press Plan "
        + "again.";

    /// <summary>
    /// What `remodel.start` answers while Start is switched off in this build (004 T172, default
    /// taken 2026-09-26, the owner may revise; research R13.3): until the workstation probes that
    /// decide whether a Start is safe have verdicts, Plan runs and Start is refused.
    ///
    /// By <see cref="SessionLostMessage"/>'s rules: no command, no path, and no probe number -
    /// the engineer cannot act on one. It says Start is not switched on yet, that the two other
    /// buttons still work, by the labels the page gives them, and that nothing was changed.
    /// </summary>
    public const string StartNotValidatedMessage =
        "Start is not switched on in this build yet, so this plan cannot be applied to the copy. "
        + "Remodel a copy and Discard copy still work, and the plan stays in its run folder. "
        + NothingWasChanged;

    /// <summary>
    /// What a plan closed by planning again is told with (004 T173, default taken 2026-09-26, the
    /// owner may revise; research R13.4): its `remodel.plan_lost` notice, its
    /// `init.latest_run.plan_lost`, and the `SessionLost` a Start naming it gets. In
    /// <see cref="SessionLostMessage"/>'s plain words, and naming the button the notice offers.
    /// </summary>
    public const string PlanClosedMessage =
        "This plan was set aside when a new plan was asked for, so it can no longer be started. "
        + PartNotChanged + " Make your part the active document and press Plan again.";

    /// <summary>
    /// What `remodel.plan` answers when the active document is one of the re-modeler's own copies
    /// (004 T173): a part in a run folder's <c>copy</c> folder under the run root. It names no
    /// path and sends the engineer back to their own part, by the label of the button they press.
    /// </summary>
    public const string SourceIsRemodelCopyMessage =
        "The active document is a copy the re-modeler made, not your own part. Make your own part "
        + "the active document and press Remodel a copy again.";

    /// <summary>
    /// What `remodel.plan` answers when the active document, read again once the settings-restart
    /// gate has marked the host busy, is not the one the press was for (owner decision 145A, found on
    /// review): the gate can wait through a restart, and the engineer can switch documents - or
    /// configurations - meanwhile. True of a configuration switched alone, and of an earlier plan
    /// waiting for Start, which is kept (third review). No path: the tab says whose document it
    /// means without one.
    /// </summary>
    public const string DocumentChangedMessage =
        "The active document or its configuration changed after Remodel a copy was pressed, so nothing "
        + "was copied and no new plan was made. " + PartNotChanged + " Make your part the active document "
        + "and press Remodel a copy again.";

    /// <summary>
    /// What the page's run status line is told before a plan whose gate meets a settings restart
    /// that waits or is being made (owner decision 145A, found on review). Posted as
    /// `status {stage: "backend_starting"}`. Its beginning, <see cref="PaneActions.WaitingForTheRestart"/>, is
    /// the check tabs' too since owner decision 157A, and written once there.
    /// </summary>
    public const string PlanAfterRestartMessage = PaneActions.WaitingForTheRestart + "reading the part...";

    /// <summary>...before a Start's run.</summary>
    public const string StartAfterRestartMessage = PaneActions.WaitingForTheRestart + "starting the run...";

    /// <summary>
    /// The full no-change reassurance for refusals before any copy change. Loss and cleanup
    /// notices instead use <see cref="PartNotChanged"/>, because cleanup may be late or incomplete.
    /// </summary>
    private const string NothingWasChanged = "Nothing was changed: not your part and not the copy.";

    /// <summary>The refusal class of a bridge that did not answer, as the pipeline names it.</summary>
    private const string BridgeUnavailableClass = "BridgeUnavailable";

    /// <summary>
    /// What the words of feature 004's seat adapter say where the copy may have been changed, or
    /// never existed, and so cannot be vouched for with <see cref="NothingWasChanged"/>: the
    /// engineer's own part, which nothing here ever writes, was not.
    /// </summary>
    private const string PartNotChanged = "Your part was not changed.";

    /// <summary>
    /// What `BackendRemodelPipeline.OpenCopy` refuses a plan with, as `BridgeUnavailable`, when the
    /// run folder this host just made could not be handed to the tool service before
    /// `remodel.open` (004 T158's host half): the hand-over answered false or threw, so nothing
    /// was copied and no open was sent.
    ///
    /// In the engineer's words, like <see cref="SessionLostMessage"/>: no command, no path, none
    /// of the build's plumbing, and the button that is the way back by its label. The Remodel page
    /// reads no words file, so this constant is its words source, printed verbatim.
    /// </summary>
    public const string RunNotBoundMessage =
        "The add-in could not reach SOLIDWORKS to get the copy ready, so nothing was copied. "
        + PartNotChanged + " Wait a moment and press Remodel a copy again.";

    /// <summary>
    /// Owner decision 148A (feature 011 research R12.4): `remodel.open_copy`'s refusal while a remodel run
    /// is in progress, `RunInProgress`. Opening or activating the copy between the run's requests to the
    /// bridge would change the document SOLIDWORKS has active under the run. In the engineer's words, with
    /// no path, naming the button that works once the run has finished by its label.
    /// </summary>
    public const string OpenCopyWhileARunIsInProgressMessage =
        "The copy is not opened while a remodel run is in progress: opening it would change the "
        + "document SOLIDWORKS has active under the run. Press Open copy again once the run has finished.";

    /// <summary>
    /// Owner decision 155A (004 research R18): what the tab says for `DocumentDirty`, whoever refused - this
    /// host's own reading of the probe's signals, or the bridge's probe or its reading of the part again
    /// inside `remodel.open`, before the copy. The bridge's sentences name the part's full path, and the
    /// backend passes them on, so the page is given these words instead (<see cref="PageWords"/>); the
    /// bridge's sentence stays in the tool-service log's line for the request it refused. No path, the way
    /// on by the button's label, and the engineer's part vouched for alone, as the tab's other refusals of a
    /// plan do (<see cref="DocumentChangedMessage"/>).
    /// </summary>
    public const string DocumentDirtyMessage =
        "Your part has unsaved changes, and the re-modeler copies the part as it is saved on disk, so "
        + "nothing was copied and no new plan was made. " + PartNotChanged + " Save it, or close it "
        + "without saving and open it again, then press Remodel a copy again.";

    /// <summary>
    /// Owner decision 155A: what the tab says for `ExternalReferences`, whoever refused, by
    /// <see cref="DocumentDirtyMessage"/>'s rules. It names no button: pressing again changes nothing, and
    /// breaking the part's references is a change to the engineer's own part, which this tab does not ask
    /// for.
    /// </summary>
    public const string ExternalReferencesMessage =
        "This part references other files, which this remodel cannot copy with it, so nothing was "
        + "copied and no new plan was made. " + PartNotChanged + " This version remodels only parts "
        + "that reference no other files.";

    /// <summary>
    /// Owner decision 155A: what every row that looks a run up answers for a run folder this host has no
    /// record of (`RunNotFound`) - Start, the result, Open copy, Discard copy, Show and the shared rows'
    /// lookup - where it named the folder the page sent. A host keeps its runs for as long as it lives, so
    /// a page naming one it does not have is showing a run from before it.
    /// </summary>
    public const string RunNotFoundMessage =
        "This tab no longer has that run, so nothing was done with it. Press Remodel a copy to plan again.";

    /// <summary>
    /// Owner decision 155A: what the page is told when the copy goes away while a run is in progress (RK-14)
    /// and the run is stopped, where it named the copy's full path. Told as the engineer's own Stop is told,
    /// a stage the page shows in its run line while the run goes on to its end (<see cref="DocumentChanged"/>).
    /// </summary>
    public const string CopyGoneMessage =
        "The copy is gone, so the run is stopping: the change in flight is finished first, and the "
        + "change log stays in the run folder. " + PartNotChanged + " Once the run has ended, press "
        + "Remodel a copy to plan again.";

    // ---- owner decision 159A: the tab's words for a failure whose own sentence can name a path ----------
    //
    // Each is what the page prints in place of a failure's own sentence - a refusal the review backend
    // answered, an exception, a restart's or a start's failure - which can name the part's, the run folder's,
    // the log's or the bridge's pipe's full path (004 research R19). The failure's own sentence goes to the
    // add-in's log (RemodelHostOptions.Log), which View log opens, and never to the tab.

    /// <summary>How the tab's words send whoever needs the failure's own sentence to the log, by the button's label.</summary>
    private const string PressViewLog = "Press View log to see why.";

    /// <summary>
    /// Owner decision 159A: a failure the add-in did not expect - an exception rather than a named refusal, in
    /// a plan, a Start, a run or any other message - in place of its message, which can name a path (the
    /// pipeline's refusal of a dump that read another document, a file the disk refused, SOLIDWORKS' refusal
    /// of a drawing). The reply's class stays `HostError`.
    /// </summary>
    public const string UnexpectedFailureMessage =
        "The add-in met a failure it did not expect, so what was asked was not done. " + PartNotChanged + " "
        + PressViewLog;

    /// <summary>
    /// Owner decision 159A: `NotAPart` as the review backend answers it, from the bridge's probe or its reading
    /// of the part again before the copy: the active document, which this host saw as a part, is not a part file
    /// at the path SOLIDWORKS opened it from. The bridge's sentence names that path. This host's own `NotAPart`,
    /// for an assembly or a drawing, keeps its words.
    /// </summary>
    public const string NotAPartOnDiskMessage =
        "The active document is not a part file the re-modeler can find where SOLIDWORKS opened it from - it may "
        + "have been moved, renamed or deleted since - so nothing was copied and no new plan was made. "
        + PartNotChanged + " Save it as a part, then press Remodel a copy again.";

    /// <summary>
    /// Owner decision 159A: `BridgeUnavailable` as the review backend answers it - the bridge did not answer one
    /// of its routes, or its circuit is open - whose sentence carries the transport's, naming the bridge's pipe.
    /// The add-in's own refusals of the class (<see cref="RunNotBoundMessage"/>, a tool service not listening yet)
    /// keep their words.
    /// </summary>
    public const string BridgeNotAnsweringMessage =
        "SOLIDWORKS did not answer the re-modeler, so it stopped. " + PartNotChanged
        + " Wait a moment, then press Remodel a copy again.";

    /// <summary>
    /// Owner decision 159A: `BackendUnavailable` as the add-in's client of the review backend answers it - the
    /// backend is not running, or did not answer a call - whose sentence carries the transport's own.
    /// </summary>
    public const string BackendNotAnsweringMessage =
        "The review backend did not answer, so the re-modeler stopped. " + PartNotChanged
        + " Wait for the backend to be ready, then press Remodel a copy again.";

    /// <summary>
    /// Owner decision 159A: every other refusal the review backend answers, whose sentence can name the part's or
    /// the run folder's full path - `RunFolderFailed` (the bridge's `source_not_open`, the copy's own refusals,
    /// every code with no row of its own, the open record and the waivers), `PackageMissing`, `NotModelCheck`,
    /// `RunNotPlanned`, `ResumeRefused` and `RunInProgress` from `POST /remodel/runs`, `PackageAfterRefused`,
    /// `InvalidRunDir`, and any class this build has no words for; and the backend's own word, in the run line,
    /// that a run failed. True of every step it can stop - before any change to a copy, or during a run, whose
    /// last word follows it.
    /// </summary>
    public const string BackendFailedMessage =
        "The review backend could not do a step of this remodel, so it stopped. " + PartNotChanged
        + " Press View log to see why, then press Remodel a copy to plan again.";

    /// <summary>
    /// Owner decision 159A: `RunFolderFailed` as this host raises it - the run folder could not be made under the
    /// run root - where it named the run root and carried the disk's refusal, which names the folder too.
    /// </summary>
    public const string RunFolderNotMadeMessage =
        "The run folder could not be made under the run root, so nothing was copied and no new plan was made. "
        + PartNotChanged + " Press View log to see why; if the run root cannot be written to, choose a local folder "
        + "for runs in Settings on the Review tab, then press Remodel a copy again.";

    /// <summary>
    /// Owner decision 159A: `BridgeUnavailable` when the close of an earlier plan waiting for Start failed with no
    /// named refusal (004 T173), where the sentence ended with the failure's own message. On review (the mutation
    /// review's M3 and M6): every close of that plan that was not answered, the bridge's own `BridgeUnavailable` and a
    /// close that never reached the bridge included, in words that say what is known rather than who did not answer.
    /// </summary>
    public const string EarlierPlanNotClosedMessage =
        "Closing the earlier plan's copy was not confirmed, so that plan is left as it was and no new plan was made. "
        + PartNotChanged + " Wait a moment, then press Remodel a copy again.";

    /// <summary>
    /// Owner decision 159A (004 research R22): what `remodel.plan_lost`, `init.latest_run.plan_lost` and a Start's
    /// `SessionLost` say of a plan whose session the host closed before a settings restart moved the run root - the
    /// backend in force is the only one that accepts its folder - in <see cref="PlanLostMessage"/>'s plain words. True
    /// whether or not that restart then succeeded: the plan's session is over either way.
    /// </summary>
    public const string PlanClosedForRunRootMessage =
        "This plan was closed so that the run root saved in Settings could come into force, so it can no longer be "
        + "started. " + PartNotChanged + " Make your part the active document and press Plan again.";

    /// <summary>004 T258: a failed plan's cleanup still unanswered, before a new probe or copy.</summary>
    public const string FailedPlanNotClosedMessage =
        "Closing the copy from the earlier attempt was not confirmed, so no new plan was made. "
        + PartNotChanged + " Wait a moment, then press Remodel a copy again.";

    /// <summary>The run's first word, as Start hands the run to the pipeline.</summary>
    public const string RunningThePlanMessage = "Running the plan against the copy...";

    /// <summary>
    /// Owner decision 159A, on the final review (S2): a plan refused because the close of the copy the earlier run left
    /// open - its own close not answered, its backend gone - is still not answered: one bridge holds one session, so no
    /// copy can be opened until that one is closed. Plain words, no path; the close's failure goes to the log.
    /// </summary>
    public const string EarlierRunNotClosedMessage =
        "Closing the copy the earlier run left open was not confirmed, so no new plan was made. "
        + PartNotChanged + " Wait a moment, then press Remodel a copy again.";

    /// <summary>
    /// Owner decision 159A: the run's last word when the close of its session was not answered (004 T180), where it
    /// ended with the failure's own message. On review (the mutation review's M6): a close that never reached the bridge
    /// included, in words that say what is known rather than who did not answer.
    /// </summary>
    public const string RunCloseNotAnsweredMessage =
        "The run ended, but closing its copy was not confirmed, so the copy may still be open in SOLIDWORKS; the report "
        + "and the saved artifacts are kept. " + PartNotChanged + " " + PressViewLog;

    /// <summary>
    /// Owner decision 159A: `OpenFailed` for Open copy - SOLIDWORKS would not open or activate the copy, or answered
    /// with another document - where the seat's sentence named the copy's full path.
    /// </summary>
    public const string OpenCopyFailedMessage =
        "SOLIDWORKS did not open the copy, so nothing was opened. " + PartNotChanged
        + " Press View log to see why, then press Open copy again.";

    /// <summary>
    /// Owner decision 159A: `DiscardFailed` when the copy could not be deleted - SOLIDWORKS has it open, most often -
    /// where the disk's refusal named the copy's full path.
    /// </summary>
    public const string DiscardCopyFailedMessage =
        "The copy could not be deleted, so it is still in the run folder; SOLIDWORKS may still have it open. "
        + PartNotChanged + " Close the copy in SOLIDWORKS without saving, then press Discard copy again. "
        + PressViewLog;

    /// <summary>
    /// Owner decision 159A: `DiscardFailed` when the copy was deleted and `plan.json` would not take its new state,
    /// where the sentence ended with the disk's refusal, which names the file's full path.
    /// </summary>
    public const string DiscardStateNotWrittenMessage =
        "The copy was deleted, but 'discarded' could not be written to plan.json, so this tab would go on reporting "
        + "the state the run ended in. " + PartNotChanged + " " + PressViewLog;

    /// <summary>
    /// Owner decision 159A: the settings-restart gate's `BackendUnavailable`, retryable, for a plan or a Start - the
    /// restart the press made or waited for failed, whose failure can end in the backend's log's path (decision
    /// 150A), or the backend did not answer whether a turn runs - which leave the backend not restarted with the
    /// saved settings. The gate's other refusals keep their words.
    /// </summary>
    public const string BackendNotRestartedMessage =
        "The review backend has not restarted with the saved settings, so nothing was done. " + PartNotChanged
        + " Save the settings again on the Review tab to restart it, then try again. " + PressViewLog;

    /// <summary>
    /// Owner decision 159A: the add-in's word that the backend did not start - a first start, or a settings restart
    /// once the old backend had stopped - posted `status {stage: "error", lifecycle: true}`, where it carried the
    /// failure, which can end in the backend's log's path (decision 150A). The Review tab shows the failure whole.
    /// </summary>
    public const string BackendDidNotStartMessage =
        "The review backend did not start, so this tab cannot plan or run. The Review tab says why. "
        + ReviewHost.StartItAgainOnTheReviewTab;

    /// <summary>
    /// Owner decision 159A: Show change's `entity.shown {ok: false}` when showing threw - SOLIDWORKS did not answer,
    /// or refused to attach while a drawing was active - where it carried the failure, which can name the drawing's
    /// full path.
    /// </summary>
    public const string ShowFailedMessage =
        "SOLIDWORKS could not show this, so nothing was selected. " + PressViewLog;

    /// <summary>Owner decision 159A: `OpenFailed` for Open report and Open run folder, where it carried Windows' refusal.</summary>
    public const string NotOpenedMessage = "Windows could not open it, so nothing was opened. " + PressViewLog;

    /// <summary>
    /// Owner decision 159A: `OpenFailed` for View log, where it carried the refusal to make the log folder, which names
    /// the folder: the log could not be written there either.
    /// </summary>
    public const string LogFolderNotOpenedMessage = "Windows could not open the log folder, so nothing was opened.";

    /// <summary>
    /// The reason both of 004 T159's refusals give: the copy could not be made the active document
    /// before a dump - SOLIDWORKS does not have it open, would not activate it, had another
    /// document active afterwards, or no copy was left to activate - so it was not read, since a
    /// dump reads whatever is active.
    /// </summary>
    private const string CopyNotRead =
        "SOLIDWORKS could not make the copy the active document - it may have been closed - so the "
        + "copy was not read";

    /// <summary>
    /// `CopyNotActive` before the plan (004 T159): the dump `package-before.json` comes from was
    /// not taken, so there is no plan. The copy on disk is still the byte copy the open made, so
    /// <see cref="NothingWasChanged"/> holds, and Remodel a copy plans again with a new copy.
    /// </summary>
    public const string CopyNotActiveBeforePlanMessage =
        CopyNotRead + " and there is no plan. " + NothingWasChanged
        + " Press Remodel a copy to plan again.";

    /// <summary>
    /// `CopyNotActive` after the changes (004 T159): `package-after.json` was not taken, so the
    /// run cannot be checked and the copy is never saved. The changes were made to the copy, so
    /// this says the engineer's part was not changed, and no more.
    /// </summary>
    public const string CopyNotActiveAfterChangesMessage =
        CopyNotRead + " after the changes. The run cannot be checked, and the copy was not saved. "
        + PartNotChanged;

    /// <summary>The first two sentences of every teardown failure (004 T167).</summary>
    private const string NotEverythingPutBack =
        "Not everything the plan changed in SOLIDWORKS could be put back. " + PartNotChanged;

    /// <summary>Where the three toggles the run changes live in SOLIDWORKS' own dialog.</summary>
    private const string GeneralOptions = "Tools > Options > System Options > General";

    /// <summary>
    /// `CommandInProgress`, which has no Tools > Options label, by what it does and how it clears
    /// (INFERRED: it is per session, so a restart clears it; a seat item).
    /// </summary>
    private const string MessagesMayStayHidden =
        "SOLIDWORKS may keep some of its messages hidden until you restart it.";

    /// <summary>A copy the teardown did not close, by its suffix and never by its path.</summary>
    private const string CopyMayStillBeOpen =
        "The copy may still be open in SOLIDWORKS (its name ends in " + RemodelCopy.CopySuffix
        + "): close it without saving.";

    /// <summary>
    /// The Tools > Options > System Options > General label of each toggle the run changes
    /// (<see cref="RemodelSystemToggles.SuppressedToggles"/>), as
    /// `docs/test-plan-2026-09-27/workstation-test-plan.md` step 1 already asks the engineer to read them.
    /// Whether 2024 spells them so is a seat item (research R13.8, D8).
    /// </summary>
    private static readonly Dictionary<int, string> ToggleLabels = new Dictionary<int, string>
    {
        { RemodelSystemToggles.InputDimValOnCreate, "Input dimension value" },
        { RemodelSystemToggles.ShowErrorsEveryRebuild, "Show errors every rebuild" },
        { RemodelSystemToggles.WarnSaveUpdateErrors, "Warn before saving documents with update errors" },
    };

    /// <summary>
    /// A setting the routine reports that is none of <see cref="ToggleLabels"/>' toggles: no
    /// <c>swUserPreferenceToggle_e</c> value is negative, so this can never be one of them.
    /// </summary>
    private const int UnlabelledSetting = int.MinValue;

    /// <summary>The only scope this feature reorganizes. Parts only, by owner decision.</summary>
    private const string PartKind = "part";

    /// <summary>What `plan.json` says a run that has only been planned is.</summary>
    private const string PlannedState = "planned";

    /// <summary>What `plan.json` says a run whose copy the engineer deleted is.</summary>
    private const string DiscardedState = "discarded";

    /// <summary>The member of `plan.json` that carries the run state: one name for the reader
    /// and the writer of it.</summary>
    private const string StateMember = "state";

    /// <summary>The folder inside a run folder that the copy - and only the copy - lives in.</summary>
    private const string CopyFolderName = RemodelCopy.CopyFolderName;

    private readonly RemodelHostOptions _options;
    private readonly PaneActions _actions;
    private readonly List<RemodelRun> _runs = new List<RemodelRun>();
    private readonly object _runsLock = new object();

    /// <summary>
    /// 004 T258: the run folder and original attachment of an unsuccessful plan whose cleanup was
    /// not answered. It is not a planned run and must not replace the page's latest successful plan.
    /// Plan reads and writes this record while it holds the host and the tool service; owner decision
    /// 159A (004 research R22): so does a restart that moves the run root
    /// (<see cref="EndTheSessionsLeftUnder"/>), under the restart's own lock, while the host is free and no
    /// plan can make it busy. Volatile, since the two run on different threads. Since 004 research R22.13, the end of
    /// its session (<see cref="SessionEnded(RemodelSessionEnd)"/>) lets it go too, by compare-and-swap of that exact record.
    /// </summary>
    private volatile Tuple<string, string?>? _failedPlanToClose;

    /// <summary>
    /// Owner decision 159A (004 research R22.14, Codex's fifth review): the run folder of the plan attempt from its open to
    /// its end, and whether the bridge has told the end of that attempt's session meanwhile - the failed open's unwind, or
    /// the backend's own close inside a plan step that fails - before the attempt has any record to clear. Written with
    /// the failed plan's record under <see cref="_attemptLock"/>, so an end lands either before the record, and none is
    /// made, or after it, and <see cref="SessionEnded(RemodelSessionEnd)"/> lets it go.
    /// </summary>
    private readonly object _attemptLock = new object();

    /// <summary>
    /// The latest attempt's run folder (<see cref="_attemptLock"/>), null before the first. Left as it is once a plan ends:
    /// each attempt writes both fields at its open, and only that attempt reads them.
    /// </summary>
    private string? _attemptRun;

    /// <summary>Whether the bridge told the end of <see cref="_attemptRun"/>'s session (<see cref="_attemptLock"/>).</summary>
    private bool _attemptEnded;

    /// <summary>A plan or a run is in flight. One per host.</summary>
    private volatile bool _busy;

    /// <summary>
    /// Owner decision 152A, on the Codex review (X2): the hold on the tool service's attachment the plan
    /// or run that made the host busy took (<see cref="RemodelHostOptions.HoldToolService"/>), and null
    /// while the host is free. Let go with <see cref="_busy"/>, by whichever thread frees the host.
    /// </summary>
    private IDisposable? _toolServiceHold;

    /// <summary>The run the executor is inside, so `remodel.stop` has something to set.</summary>
    private volatile RemodelRun? _active;

    /// <summary>
    /// Every `remodel.stop` that reached the run in flight, waiting for the executor to finalize, each
    /// answered once at the run's end (owner decision 159A: Stop stays pressable until the run ends, and
    /// a second press no longer replaces the first). Guarded by <see cref="_endingLock"/>, and taken as
    /// the host is freed, so none outlives its run.
    /// </summary>
    private readonly List<string?> _pendingStops = new List<string?>();

    /// <summary>
    /// Owner decision 155A (004 research R18): orders the end of a run - the host freed from it - with what
    /// an `init` reads of a run in flight and posts (<see cref="SendInit"/>), and with what the run's ending
    /// holds back meanwhile (<see cref="HoldUntilTheHostIsFree"/>). Held only to read and write the run's
    /// fields and to post, which queues the message to the pane and returns, so nothing under it waits on
    /// another thread: SOLIDWORKS' application thread takes it too, when a session's ending is told during
    /// a run (<see cref="PostWhatWasLeft"/>), and a wait on that thread under it could hang SOLIDWORKS.
    /// Owner decision 159A (004 research R19): a stop - the engineer's (<see cref="Stop"/>) or the copy
    /// going away (<see cref="DocumentChanged"/>) - is decided and told under it too, so it reaches the run
    /// before its end or finds the host free.
    /// </summary>
    private readonly object _endingLock = new object();

    /// <summary>
    /// Owner decision 155A: what a run's ending tells the page while the run still holds the host - a
    /// `status` the page ends its running state on (`ready`, `error`), and the refusal posted beside one -
    /// in the order it was made, told by <see cref="Execute"/> once the host is free. Guarded by
    /// <see cref="_endingLock"/>.
    /// </summary>
    private readonly List<Action> _heldForTheEnd = new List<Action>();

    /// <summary>
    /// The host as shipped: Start is switched on or off by <see cref="RemodelStart.SeatValidated"/>
    /// (004 T172).
    /// </summary>
    public RemodelHost(RemodelHostOptions options)
        : this(options, RemodelStart.SeatValidated)
    {
    }

    /// <summary>
    /// The host with the Start switch given, as <c>DrawingOpenScope</c> takes its own: the tests
    /// of a Start pass true, and the tests of the switch pass what they mean.
    /// </summary>
    /// <param name="options">Everything the host is given.</param>
    /// <param name="startValidated">004 T172: false refuses every `remodel.start` with
    /// `StartNotValidated`, before any call.</param>
    public RemodelHost(RemodelHostOptions options, bool startValidated)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));
        StartValidated = startValidated;
        _actions = new PaneActions(new PaneActionsOptions(
            options.Channel,
            options.RunRoot,
            new PaneRunLookup(
                "run_dir",
                "RunNotFound",
                _ => RunNotFoundMessage,
                runDir => FindRun(runDir)?.RunDirectory))
        {
            RunRootsInForce = () => options.RunRootsInForce(),
            RunRootSaved = () => options.RunRootSaved(),
            RunRootProbe = () => options.RunRootProbe,
            LogFolder = options.LogFolder,
            EntityResolver = options.EntityResolver,
            Opener = options.Opener,
            Secrets = options.Secrets,

            // Owner decision 159A (004 research R19): a failure the shared rows caught - Windows that would not open
            // a file or a folder, SOLIDWORKS that would not show a change - in this tab's words, its message logged.
            FailureWords = SharedRowWords,
        });
    }

    /// <summary>The runs this host planned, oldest first.</summary>
    public IReadOnlyList<RemodelRun> Runs
    {
        get
        {
            lock (_runsLock)
            {
                return _runs.ToArray();
            }
        }
    }

    /// <summary>
    /// 004 T172: whether Start may run in this build. While false, `remodel.start` is refused
    /// `StartNotValidated` after `ResumeRefused` and before `SessionLost`, and the bridge refuses
    /// the change commands as the backstop.
    /// </summary>
    public bool StartValidated { get; }

    /// <summary>
    /// Whether a plan or a run is in flight - the same fact `remodel.plan` refuses a second
    /// one on. Read by <see cref="SwReview.AddIn.ToolService.ToolServiceGate.FollowDocument"/>:
    /// every write the run makes goes through the bridge, so restarting the tool service
    /// underneath one would fail it mid-copy.
    ///
    /// A plan waiting for Start is <b>not</b> in progress and holds nothing (decision 22A): a
    /// document switch between the plan and Start re-attaches the tool service, the plan's
    /// bridge session goes with the old attachment, and `remodel.start` refuses that plan as
    /// `SessionLost` rather than start it on a dispatcher that never saw its copy. The page is
    /// told at the re-attach itself, before Start (decision 24A, <see cref="AnnounceLostPlan"/>).
    ///
    /// Read too by the review host's settings restart, which waits while it is true (owner
    /// decision 145A): it is set only through <see cref="RemodelHostOptions.BeginRun"/>, under that
    /// restart's own lock, so a restart and a plan or a run never overlap.
    /// </summary>
    public bool RunInProgress => _busy;

    /// <summary>The newest run, or null before the first `remodel.plan`.</summary>
    public RemodelRun? LatestRun { get; private set; }

    /// <summary>
    /// The run <paramref name="key"/> names, or null.
    ///
    /// The key is the run folder or the run id, and it is matched against this host's own
    /// records: a page that could name a folder this host never created could ask for anything
    /// on the workstation to be opened.
    /// </summary>
    public RemodelRun? FindRun(string? key)
    {
        string trimmed = (key ?? string.Empty).Trim();
        if (trimmed.Length == 0)
        {
            return null;
        }

        string normalized = trimmed.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        lock (_runsLock)
        {
            return _runs.FirstOrDefault(run =>
                string.Equals(run.RunDirectory, normalized, StringComparison.OrdinalIgnoreCase)
                || string.Equals(run.RunId, normalized, StringComparison.OrdinalIgnoreCase));
        }
    }

    /// <summary>Handles one message from the page. Never throws.</summary>
    public void Receive(string json)
    {
        string? id = null;
        string? type = null;
        try
        {
            using (JsonDocument document = JsonDocument.Parse(json))
            {
                JsonElement root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object)
                {
                    throw new FormatException("a page message must be a JSON object");
                }

                id = PagePayload.Text(root, "id");
                type = PagePayload.Text(root, "type");
                if (string.IsNullOrEmpty(type))
                {
                    throw new FormatException("a page message must carry a 'type'");
                }

                JsonElement payload = root.TryGetProperty("payload", out JsonElement value)
                    ? value
                    : default;
                Dispatch(type!, id, payload);
            }
        }
        catch (RemodelRefusal refusal)
        {
            // Before the catch below, and that order is the whole point: the pipeline's members
            // return readings rather than error objects, so a refusal the backend or the bridge
            // named travels out of them as an exception with its class attached. Answered as
            // `HostError` it would read to the engineer as a bug in the pane rather than as the
            // condition of the part it is (`contracts/pane-remodel-messages.md`, refusal classes).
            SendRefusal(id, refusal, type ?? "a page message");
        }
        catch (Exception failure)
        {
            // An exception escaping into the `WebMessageReceived` handler would surface inside
            // SOLIDWORKS. Owner decision 159A (004 research R19): its message can name a path - a
            // file the disk refused, the pipeline's refusal of a dump that read another document - so
            // it goes to the log, and the page is told in this tab's words.
            Log(type ?? "a page message", failure);
            _actions.SendError(id, "HostError", UnexpectedFailureMessage, retryable: false);
        }
    }

    /// <summary>Sends an unsolicited message (`status`, `document.changed`, `backend.stopped`).</summary>
    public void Post(string type, object? payload) => _actions.Send(type, null, payload);

    /// <summary>Posts one `status`, with every secret masked out of it (FR-015).</summary>
    public void PostStatus(string stage, string message) => _actions.PostStatus(stage, message);

    /// <summary>
    /// <see cref="PostStatus(string, string)"/>, marked as the add-in's own word on the backend when <paramref name="lifecycle"/>
    /// (owner decision 145A). Owner decision 159A (004 research R19): that word's `error` - the backend did not start, a
    /// first start or a settings restart once the old backend had stopped - carries the failure, which can end in the
    /// backend's log's path (decision 150A); this tab tells it in <see cref="BackendDidNotStartMessage"/>. On review: the
    /// failure is not logged here. Those words send the engineer to the Review tab, which shows it whole, and the add-in's
    /// own report of a first start that failed logs it (<c>SwReviewAddIn.StartBackend</c>); a second line was the same
    /// failure twice.
    /// </summary>
    public void PostStatus(string stage, string message, bool lifecycle)
    {
        if (lifecycle && string.Equals(stage, "error", StringComparison.Ordinal))
        {
            _actions.PostStatus(stage, BackendDidNotStartMessage, lifecycle);
            return;
        }

        _actions.PostStatus(stage, message, lifecycle);
    }

    /// <summary>
    /// Tells the page the backend was restarted with saved settings, so it asks `ready` again for
    /// the new port and token (owner decision 145A). This page makes no call of its own - its
    /// backend work is this host's, which reads the endpoint per call - but it keeps them, so one
    /// `init` field means one thing on every tab. The add-in calls it after every restart the
    /// review host makes. No sentence travels with it: the Review tab's sentences about a restart
    /// that waited are shown on the Review tab alone.
    /// </summary>
    public void BackendRestarted() => _actions.PostBackendRestarted(Array.Empty<string>());

    /// <summary>
    /// The `status` stages this page has a branch for, closed by
    /// `contracts/pane-remodel-messages.md`.
    ///
    /// On the Review and Model check tabs `status` reports the backend's lifecycle; here it is
    /// the run's own phase strip, which is why the remodel contract's row does not carry
    /// `backend_starting` where feature 002's `pane-host-messages.md` and feature 003's
    /// `model-check.md` do. `SwReviewAddIn.PostStatusToPages` fans one backend-lifecycle
    /// `status` out to all three pages and filters this page's share through
    /// <see cref="IsStatusStage"/>, so a stage the page cannot show is never posted to it.
    /// `ready` and `error` are on both lists and do arrive - which is what lets a Remodel tab
    /// opened while the backend was still starting ask for its `init` again.
    /// </summary>
    public static IReadOnlyCollection<string> StatusStages => Stages;

    /// <summary>Whether <paramref name="stage"/> is on <see cref="StatusStages"/>.</summary>
    public static bool IsStatusStage(string stage) => stage != null && Stages.Contains(stage);

    private static readonly HashSet<string> Stages = new HashSet<string>(
        new[]
        {
            "copying",
            "dumping",
            "planning",
            "judging",
            "applying",
            "verifying",
            "saving",
            "backend_starting",
            "ready",
            "error",
        },
        StringComparer.Ordinal);

    /// <summary>
    /// Tells the page which document the pane is looking at now - and aborts a run whose copy
    /// has gone away.
    ///
    /// RK-14: the engineer closes or deletes the copy mid-run. The stop flag is set, so the
    /// executor finishes the change in flight, inverts it if it failed and finalizes, leaving
    /// the change log intact. A `document.changed` that names the copy itself is the ordinary
    /// case - `remodel.open_copy` causes one - and changes nothing.
    /// </summary>
    public void DocumentChanged()
    {
        Post("document.changed", DocumentPayload(_options.CurrentDocument()));

        // Owner decision 159A (004 research R19): decided, and told, under the lock that frees the host, as the
        // engineer's Stop is, so a run that has ended is not stopped, nor told it is stopping after its last
        // word. The copy is looked for under it too: the run folder is local (owner decision 154A), so the look
        // waits on no other thread.
        lock (_endingLock)
        {
            RemodelRun? run = _active;
            if (run == null || run.StopRequested || CopyExists(run))
            {
                return;
            }

            run.RequestStop();

            // Owner decision 155A: in plain words, naming no path - the run folder holds the copy's - and
            // told as the engineer's own Stop is told, in a stage the page shows in its run line while the
            // run goes on to its end, not in one that ends the page's running state while the run still
            // finishes the change in flight and holds the host.
            run.RememberStatus("applying", CopyGoneMessage);
            PostStatus("applying", CopyGoneMessage);
        }
    }

    /// <summary>
    /// Refreshes the page's capability banner when the tool service finishes attaching or
    /// detaches. It uses the existing document message so no new page protocol row is needed.
    ///
    /// It is also where this host sees a re-attach (decision 24A): the add-in calls it each time
    /// its gate withdraws a service and each time a new one listens. A withdrawal refreshes only
    /// capability; after the Dispose attempt the gate allows the lost-plan notice. Explicit
    /// same-attachment session endings also use the same loss predicate.
    /// </summary>
    public void RefreshAvailability(bool announceLostPlan = true)
    {
        Post("document.changed", DocumentPayloadWithCapability(_options.CurrentDocument()));
        if (announceLostPlan)
        {
            AnnounceLostPlan();
        }
    }

    /// <summary>
    /// T180: preserve only a planned copy whose exact held session belongs to this attachment.
    /// A path merely under copy/ is never sufficient, nor is a copy from a completed or closed run.
    /// </summary>
    public bool KeepCopyAttachment(string activePath, string? attachment)
    {
        RemodelRun? run = LatestRun;
        return run != null
            && run.Phase == RemodelRunPhase.Planned
            && !run.CopyDiscarded
            && HoldsItsSession(run, attachment)
            && SamePath(run.CopyPath, activePath);
    }

    private static bool SamePath(string? left, string? right)
    {
        if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right))
        {
            return false;
        }

        try
        {
            return string.Equals(
                Path.GetFullPath(left).TrimEnd('\\', '/'),
                Path.GetFullPath(right).TrimEnd('\\', '/'),
                StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>
    /// What a teardown that ended a remodel session left behind, told to the page (004 T167):
    /// one `status {stage: "error"}` carrying <see cref="SessionEndedMessage"/>, and nothing at
    /// all when everything was put back and the copy was closed, because then the plan is lost
    /// exactly as decision 24A already tells the page. Loss words promise only that the original
    /// part was not changed; a late or incomplete teardown cannot justify a broader promise.
    ///
    /// The add-in calls <see cref="SessionEnded(RemodelSessionEnd)"/> from
    /// `ToolServiceOptions.RemodelSessionEnded`, which reads the bridge routine's outcome onto the
    /// three facts the words need (`contracts/pane-remodel-messages.md`, "When a re-attach or an
    /// unload ends the session"). It never throws: it is called from the tool service's teardown,
    /// and a page that cannot be told is no reason for that to fail.
    /// </summary>
    /// <param name="togglesNotRestored">The <c>swUserPreferenceToggle_e</c> values the routine
    /// could not put back; null is none.</param>
    /// <param name="commandInProgressNotRestored">Whether <c>CommandInProgress</c> is still set.</param>
    /// <param name="copyClosed">Whether the routine closed the copy.</param>
    public void SessionEnded(
        IEnumerable<int>? togglesNotRestored, bool commandInProgressNotRestored, bool copyClosed) =>
        PostWhatWasLeft(() => SessionEndedMessage(togglesNotRestored, commandInProgressNotRestored, copyClosed));

    /// <summary>
    /// 004 T167, lanes D and E integrated: what the add-in hands on from
    /// `ToolServiceOptions.RemodelSessionEnded`, which the tool service tells every ending of a
    /// session - `remodel.close`'s (Discard, planning again) and the teardown a re-attach or an
    /// unload runs - with the end-of-session routine's outcome as it reported it. The words are
    /// <see cref="SessionEndedMessage(RemodelSessionEnd)"/>'s; null and an ending of no session
    /// are nothing. Never throws, for the reason the three-fact seam gives.
    /// </summary>
    public void SessionEnded(RemodelSessionEnd? outcome)
    {
        if (outcome != null && outcome.HadSession)
        {
            // A late teardown belongs only to the known run and copy it actually names. It must
            // not invalidate a newer plan merely because that plan is now the latest one.
            RemodelRun? run = FindRun(outcome.RunDirectory);
            if (run != null && SamePath(run.CopyPath, outcome.CopyPath))
            {
                // Owner decision 159A (004 research R22.10), and 162A (R23): the bridge tells a close's end before the close
                // is answered, so the end of a close sent before the run root moves, or by Discard, is marked as that close's here.
                RemodelCloseCause sentFor = run.CloseSentFor;
                if (sentFor != RemodelCloseCause.None && outcome.Reason == RemodelSessionEnd.ReasonClose)
                {
                    run.MarkSessionClosedFor(sentFor);
                }
                else
                {
                    run.MarkSessionEnded();
                }
            }

            // Owner decision 159A (004 research R22.13, Codex's fourth review): a failed plan is never a tracked run, so
            // the end of its session - its close's, late or not, or a teardown's - lets its record go: that exact record
            // alone, so a newer attempt's, recorded meanwhile, survives. R22.14: an end of the attempt in flight, told
            // before it has a record, marks it ended, so its failure makes none.
            lock (_attemptLock)
            {
                if (_attemptRun != null && SamePath(_attemptRun, outcome.RunDirectory))
                {
                    _attemptEnded = true;
                }
            }

            Tuple<string, string?>? failed = _failedPlanToClose;
            if (failed != null && SamePath(failed.Item1, outcome.RunDirectory))
            {
                Interlocked.CompareExchange(ref _failedPlanToClose, null, failed);
            }
        }

        PostWhatWasLeft(() => SessionEndedMessage(outcome));
        if (outcome != null && outcome.HadSession)
        {
            RemodelRun? ended = FindRun(outcome.RunDirectory);
            if (ended != null && SamePath(ended.CopyPath, outcome.CopyPath)
                && SameAttachment(ended.ToolServiceAttachment, _options.ToolServiceAttachment()))
            {
                // Explicit closes on the current service can notify now. A withdrawn service
                // waits for the gate's afterStopped callback, after its Dispose attempt.
                AnnounceLostPlan();
            }
        }
    }

    /// <summary>
    /// The one post both seams make: the status error when there are words, nothing when there
    /// are none, and never a throw. While a run holds the host - its own close, or the run's discard
    /// of its copy, ends a session - the words wait for the run's ending, since the page ends its
    /// running state on them (owner decision 155A).
    /// </summary>
    private void PostWhatWasLeft(Func<string?> words)
    {
        try
        {
            string? message = words();
            if (message != null)
            {
                HoldUntilTheHostIsFree(() => PostStatus("error", message));
            }
        }
        catch (Exception)
        {
            // The page is gone or going (an unload), or the channel refused the post. The teardown
            // that called this has already done what it could, and the tool-service log and the
            // run's remodel.log carry its line either way.
        }
    }

    /// <summary>
    /// The routine's outcome read onto the three facts the three-fact
    /// <c>SessionEndedMessage</c> words (lanes D and E integrated; default taken 2026-09-27, the
    /// owner may revise): each setting still holding the run's value, by the name
    /// <see cref="RemodelSystemToggles.Outstanding"/> gives it - a toggle's
    /// <see cref="RemodelSystemToggles.SettingName"/> read back to its value,
    /// <c>CommandInProgress</c> apart, and a name none of the run's toggles has as a setting with
    /// no label, still said - and whether the copy was closed. Null, and an ending of no session
    /// (which set nothing and opened nothing), are null. A tag the routine could not remove is not
    /// worded: the untag reaches only the open document - an unsaved close discards the tag there, and
    /// a copy remodel.save saved keeps on disk the tag it was saved with, whatever the untag answered
    /// (004 T183) - so a failed untag changes nothing on disk, and a copy left open is already said.
    /// </summary>
    public static string? SessionEndedMessage(RemodelSessionEnd? outcome)
    {
        if (outcome == null || !outcome.HadSession)
        {
            return null;
        }

        var toggles = new List<int>();
        bool commandInProgress = false;
        foreach (string setting in outcome.SettingsOutstanding)
        {
            if (string.Equals(setting, RemodelSystemToggles.CommandInProgressSetting, StringComparison.Ordinal))
            {
                commandInProgress = true;
            }
            else
            {
                toggles.Add(ToggleNamed(setting));
            }
        }

        return SessionEndedMessage(toggles, commandInProgress, outcome.CopyClosed);
    }

    /// <summary>
    /// The toggle whose <see cref="RemodelSystemToggles.SettingName"/> is <paramref name="setting"/>,
    /// or <see cref="UnlabelledSetting"/> for a name none of the run's toggles has.
    /// </summary>
    private static int ToggleNamed(string setting)
    {
        foreach (int toggle in RemodelSystemToggles.SuppressedToggles)
        {
            if (string.Equals(RemodelSystemToggles.SettingName(toggle), setting, StringComparison.Ordinal))
            {
                return toggle;
            }
        }

        return UnlabelledSetting;
    }

    /// <summary>
    /// The words of a teardown that left something (004 T167, research R13.8 D8), or null when it
    /// left nothing: that not everything the plan changed in SOLIDWORKS could be put back and that
    /// the engineer's part was not changed; then each toggle left, by its Tools > Options label,
    /// quoted, once, in the order the run sets them, with how to put it right; a value with no
    /// label as another setting, so nothing left goes unsaid; <c>CommandInProgress</c> by what it
    /// does; and a copy that was not closed by its suffix, never its path. Every word of it is
    /// written here, in the page's one words source, so the page prints exactly what the tests pin.
    /// </summary>
    public static string? SessionEndedMessage(
        IEnumerable<int>? togglesNotRestored, bool commandInProgressNotRestored, bool copyClosed)
    {
        var left = new HashSet<int>(togglesNotRestored ?? Enumerable.Empty<int>());
        List<string> named = RemodelSystemToggles.SuppressedToggles
            .Where(left.Contains)
            .Select(toggle => "\"" + ToggleLabels[toggle] + "\"")
            .ToList();
        bool unnamed = left.Any(toggle => !ToggleLabels.ContainsKey(toggle));

        if (named.Count == 0 && !unnamed && !commandInProgressNotRestored && copyClosed)
        {
            return null;
        }

        var words = new List<string> { NotEverythingPutBack };
        if (named.Count == 1)
        {
            words.Add("The setting " + named[0] + " in " + GeneralOptions
                + " may still be as the plan left it: set it back the way you had it.");
        }
        else if (named.Count > 1)
        {
            words.Add("These settings in " + GeneralOptions + " may still be as the plan left them: "
                + string.Join(", ", named.Take(named.Count - 1)) + " and " + named[named.Count - 1]
                + ". Set them back the way you had them.");
        }

        if (unnamed)
        {
            words.Add(named.Count > 0
                ? "Another setting the plan changed may also not be as you had it."
                : "A setting the plan changed may not be as you had it.");
        }

        if (commandInProgressNotRestored)
        {
            words.Add(MessagesMayStayHidden);
        }

        if (!copyClosed)
        {
            words.Add(CopyMayStillBeOpen);
        }

        return string.Join(" ", words);
    }

    public void Dispose()
    {
        lock (_runsLock)
        {
            _runs.Clear();
            LatestRun = null;
        }
        _active = null;
    }

    private void Dispatch(string type, string? id, JsonElement payload)
    {
        // The four rows this host shares with every other pane host, answered by the one copy
        // of them.
        if (_actions.TryHandle(type, id, payload))
        {
            return;
        }

        switch (type)
        {
            case "ready":
                SendInit(id);
                return;

            case "remodel.plan":
                Plan(id);
                return;

            case "remodel.start":
                Start(id, payload);
                return;

            case "remodel.stop":
                Stop(id);
                return;

            case "remodel.result":
                SendResult(id, payload);
                return;

            case "remodel.open_copy":
                OpenCopy(id, payload);
                return;

            case "remodel.discard_copy":
                DiscardCopy(id, payload);
                return;

            case "remodel.show_change":
                ShowChange(id, payload);
                return;

            default:
                _actions.SendError(
                    id,
                    "UnknownMessage",
                    $"the host does not handle a '{type}' message",
                    retryable: false);
                return;
        }
    }

    // ---- ready / init -------------------------------------------------------------------

    /// <summary>
    /// Answers `ready` with `init`. Whether the latest run is in flight is read, and the `init` posted, under
    /// <see cref="_endingLock"/> (owner decision 155A): an `init` that reads the run in flight is posted
    /// before the host is freed from it, and so before the run's ending reaches the page, or it reads that
    /// the run is not - never told after the ending that the run is in flight, which would leave a page
    /// loaded again showing a run that has ended. Everything else is read before the lock is taken: the
    /// active document is read on SOLIDWORKS' application thread, which takes that lock when a session's
    /// ending is told during a run.
    /// </summary>
    private void SendInit(string? id)
    {
        BackendEndpoint? endpoint = _options.Backend();
        RemodelRun? latest = LatestRun;
        RemodelLimits limits = _options.Limits;
        Dictionary<string, object?>? latestRun = latest == null
            ? null
            : new Dictionary<string, object?>
            {
                { "run_dir", latest.RunDirectory },
                { "at", latest.At.ToString("o", CultureInfo.InvariantCulture) },
                { "state", StateOf(latest.RunDirectory) },

                // Decision 24A, amended on review: the notice is told once per plan,
                // and a page that loads again starts from this alone. Read afresh by
                // the notice's own rule, whatever holds the host, since `init`
                // describes the run it names; the notice's once-per-plan claim is
                // neither spent nor needed here.
                { "plan_lost", IsLostPlan(latest) ? LostMessage(latest) : null },
            };

        var init = new Dictionary<string, object?>
        {
            {
                "backend",
                endpoint == null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        { "port", endpoint.Port },

                        // The page's OWN origin under `/__backend`, as `ReviewHost` and
                        // `ModelCheckHost` send: one field, one meaning in all three
                        // contracts. This page does not fetch today - its backend work is
                        // host-side - but handing it the loopback origin would be a trap,
                        // because the page's CSP is `connect-src 'self'`, so the first fetch
                        // built from it would be refused by the renderer
                        // (docs/pane-backend-proxy.md). The port stays because the pane still
                        // shows it and a diagnostic still needs it.
                        { "origin", BackendProxy.PageOrigin },
                    }
            },
            { "token", endpoint?.Token },
            { "backend_start_failed", endpoint == null && _options.BackendStartFailed() },
            { "run_root", _options.RunRoot() },
            { "document", DocumentPayload(_options.CurrentDocument()) },
            {
                "limits",
                new Dictionary<string, object?>
                {
                    { "max_changes", limits.MaxChanges },
                    { "max_minutes", limits.MaxMinutes },
                    { "max_rebuild_seconds", limits.MaxRebuildSeconds },
                }
            },
            {
                "remodel",
                RemodelCapabilityPayload()
            },
            { "latest_run", latestRun },
        };

        lock (_endingLock)
        {
            if (latestRun != null)
            {
                // Owner decision 155A (feature 011 research R12.9 item 9): whether this run is in
                // flight - started and not yet ended - which `state`, the plan's, does not say. A page
                // that loads again starts from `init` alone, and shows the run running, Stop
                // pressable, rather than offering what the host refuses.
                bool running = ReferenceEquals(_active, latest);
                latestRun["running"] = running;

                // Owner decision 159A, on the final review: and the run's last word while it runs, which a page that
                // loads again writes where it wrote "Running..." - the backend not answering, told once, among them.
                Tuple<string, string>? said = running ? latest!.LastStatus : null;
                latestRun["status"] = said == null
                    ? null
                    : new Dictionary<string, object?> { { "stage", said.Item1 }, { "message", said.Item2 } };
            }

            _actions.Send("init", id, init);
        }
    }

    private Dictionary<string, object?> RemodelCapabilityPayload()
    {
        RemodelAvailability availability = _options.RemodelAvailability();
        return new Dictionary<string, object?>
        {
            { "available", availability == RemodelAvailability.Unknown
                ? null
                : (object)(availability == RemodelAvailability.Available) },
            { "message", availability == RemodelAvailability.Unavailable
                ? NoSeatMessage
                : availability == RemodelAvailability.Unknown
                    ? SeatCheckingMessage
                    : null },
        };
    }

    private Dictionary<string, object?>? DocumentPayloadWithCapability(PageDocument? document)
    {
        var payload = DocumentPayload(document);
        if (payload == null)
        {
            return null;
        }

        payload["remodel"] = RemodelCapabilityPayload();
        return payload;
    }

    // ---- remodel.plan -------------------------------------------------------------------

    /// <summary>
    /// Press Remodel: refuse everything that can be refused <b>before anything is copied</b>,
    /// then create the run folder, copy, open, tag, roll and rebuild the copy, dump it and run
    /// the pure planner.
    ///
    /// The order is the contract's and is not negotiable. Every refusal but one lands before a
    /// copy exists; the exception is `PreexistingRebuildErrors`, whose reading needs a rollback
    /// and a rebuild and so can only be taken on the copy - and whose handler is therefore the
    /// one that deletes a copy.
    ///
    /// Once the open was asked for, the bridge may hold a session - the copy open, the four
    /// settings changed - and a plan never leaves one behind that nothing will end: a plan that
    /// fails from there closes it before it answers (004 T175), and a plan made while Start is
    /// switched off closes it before it answers too, since no Start can use it (004 T176).
    /// </summary>
    private void Plan(string? id)
    {
        // Owner decision 154A: first - before a run in progress, the document, the seat, the gate, an earlier
        // plan's session or the probe is asked about. The run folder is made under the run root, and the backend
        // refuses one on a share and spells one reached through a link otherwise than this host binds it, so the
        // copy's open would refuse it (feature 011 research R12.9, items 1 and 2).
        string judged = _options.RunRoot();
        if (RunRootRefused(id, judged, "nothing was copied"))
        {
            return;
        }

        if (_busy)
        {
            SendRunInProgress(id);
            return;
        }

        PageDocument? document = _options.CurrentDocument();
        if (document == null)
        {
            _actions.SendError(
                id,
                "NoDocument",
                "open the part you want reorganized in SOLIDWORKS first: the re-modeler copies "
                + "the active document.",
                retryable: true);
            return;
        }

        RemodelAvailability availability = _options.RemodelAvailability();
        if (availability != RemodelAvailability.Available)
        {
            SendUnavailable(id, availability);
            return;
        }

        IRemodelPipeline? pipeline = _options.Pipeline;
        if (pipeline == null)
        {
            _actions.SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so nothing can be copied "
                + "or reorganized.",
                retryable: true);
            return;
        }

        if (!string.Equals(document.Kind, PartKind, StringComparison.Ordinal))
        {
            _actions.SendError(
                id,
                "NotAPart",
                "the re-modeler reorganizes a part's feature tree, and the active document is "
                + (document.Kind == null ? "not a SOLIDWORKS part" : "a " + document.Kind)
                + ". Open the part on its own and press Remodel again.",
                retryable: true);
            return;
        }

        // 004 T173: a copy is never a source. Checked on every Plan, before any bridge call: once
        // the pipeline activates the copy for its dump, the copy can be the active document when
        // the engineer presses Plan, and probing it would read a dirty copy of their part.
        if (IsRemodelCopy(document.Path))
        {
            _actions.SendError(id, "SourceIsRemodelCopy", SourceIsRemodelCopyMessage, retryable: true);
            return;
        }

        // Owner decision 145A: a plan holds the backend for as long as it runs, as a turn does.
        // After every refusal that needs no call, a settings restart that waits is made first - or
        // the one being made waited for - and the host is marked busy under that restart's own
        // lock, so no restart can begin under the plan; or the plan is refused, saying why.
        if (!BeganRun(id, PlanAfterRestartMessage))
        {
            return;
        }

        try
        {
            // The reviews of decision 154A, N8: the gate can make a waiting settings restart, which can bring
            // another run root into force; it is judged before anything is asked or made under it.
            string? runRoot = RunRootToUse(id, judged, "nothing was copied");
            if (runRoot == null)
            {
                return;
            }

            // Owner decision 152A, on the Codex review (X2): the plan holds the tool service before it
            // reads its attachment, so no follow takes the bridge down under it - the busy question a
            // follow asks can have been answered before this plan began. None listening to hold - none
            // started, or a follow taking one down - is refused as while the tool service attaches.
            // After the run root (merged with 154A, 2026-10-21): 154A judges the run root before anything
            // is asked or made under it, and the hold asks the tool service (corrected on the final
            // reviews, N1).
            if (!HoldTheToolService())
            {
                SendUnavailable(id, RemodelAvailability.Unknown);
                return;
            }

            // The document was read before the gate, and the gate can wait through a settings
            // restart - seconds, up to the backend's handshake - in which the engineer can make
            // another document active. Read again now the host is busy, before any call: a plan of
            // another document than the one the press was for is refused in plain words, rather
            // than met at the bridge's open as `scope_not_probed`, both paths in its words (owner
            // decision 145A, found on review).
            if (!document.IsSameDocument(_options.CurrentDocument()))
            {
                _actions.SendError(id, "DocumentChanged", DocumentChangedMessage, retryable: true);
                return;
            }

            // Decision 22A: the attachment this plan's bridge session will live on. Read once
            // the host is busy - from here the tool service begins no re-attach of its own - and
            // before the probe, so it is the attachment the probe, the copy and the session go
            // to. A re-attach that still lands while the plan runs leaves the run holding the
            // attachment it began on, and Start refuses it.
            string? attachment = _options.ToolServiceAttachment();

            // 004 T173: an earlier plan waiting for Start is ended - its session closed, the plan
            // marked lost and the page told - after every refusal that needs no call and before
            // this plan's first one, so a Plan refused on the spot costs it nothing.
            if (!EndTheFailedPlan(id, pipeline, attachment)
                || !EndTheWaitingPlan(id, pipeline, attachment))
            {
                return;
            }

            RemodelScopeReading scope;
            try
            {
                scope = pipeline.ProbeScope();
            }
            catch (Exception failure)
            {
                PostStatus("error", PageWords(failure));
                throw;
            }

            if (!ScopeAllowsARun(id, scope))
            {
                return;
            }

            string runDirectory;
            try
            {
                runDirectory = RunFolders.CreateForRemodel(runRoot, document.Path, _options.Now(), _options.RunRootProbe);
            }
            catch (Exception failure)
            {
                // Owner decision 159A (004 research R19): the run root, and the disk's refusal, named the
                // folder; this tab says it in its own words, and the refusal goes to the log.
                Log("remodel.plan", failure);
                PostStatus("error", RunFolderNotMadeMessage);
                _actions.SendError(id, "RunFolderFailed", RunFolderNotMadeMessage, retryable: false);
                return;
            }

            var reporter = new RunReporter(this, null);
            PostStatus(
                "copying",
                $"Copying {RunFolders.DocumentName(document.Path)} into the run folder...");

            lock (_attemptLock)
            {
                _attemptRun = runDirectory;
                _attemptEnded = false;
            }

            RemodelCopyReading copy;
            try
            {
                copy = pipeline.OpenCopy(
                    new RemodelCopyRequest(runDirectory, document.Path, document.Configuration),
                    reporter);
            }
            catch (Exception failure)
            {
                // The run folder is left behind on purpose: whatever it holds is the evidence
                // for why the run stopped (constitution Principle I).
                PostStatus("error", PageWords(failure));
                EndTheSessionOfAFailedPlan(pipeline, runDirectory, attachment);
                throw;
            }

            if (copy.RebuildErrorCount == null)
            {
                // Unknown is not zero. A part whose rebuild-error count could not be read is a
                // part whose baseline cannot be established, and every change after it would be
                // unattributable.
                //
                // Reported as `PreexistingRebuildErrors` rather than `ScopeRefused`, because
                // the contract makes that class the only refusal raised after the copy exists
                // and the only one whose handler deletes a copy; `ScopeRefused` is a pre-copy
                // verdict on the source. The message says the count could not be read rather
                // than that errors exist: those are different facts about the part.
                DeleteCopyFolder(pipeline, runDirectory);
                _actions.SendError(
                    id,
                    "PreexistingRebuildErrors",
                    "the rebuild-error count could not be read on the copy, so the run has no "
                    + "baseline to attribute changes against. The copy has been deleted; the "
                    + "run folder is kept.",
                    retryable: true);
                return;
            }

            if (copy.RebuildErrorCount > 0)
            {
                DeleteCopyFolder(pipeline, runDirectory);
                _actions.SendError(
                    id,
                    "PreexistingRebuildErrors",
                    $"the part already has {copy.RebuildErrorCount} rebuild "
                    + (copy.RebuildErrorCount == 1 ? "error" : "errors")
                    + ", so nothing this run did could be attributed to it. Fix the part first. "
                    + "The copy has been deleted; the run folder is kept.",
                    retryable: true);
                return;
            }

            if (!copy.CopyPresent)
            {
                // The copy is gone and the count that came back with it is 0, so the count
                // alone would let this run through - and everything after this line addresses
                // "the copy", starting with a dump that attaches to whatever document
                // SOLIDWORKS still has active. That document is the engineer's source.
                //
                // The class is the same one, because this is the same refusal: the bridge
                // raised `preexisting_rebuild_errors` and deleted the copy before it answered.
                // The message says what is known and not what the count would have implied.
                DeleteCopyFolder(pipeline, runDirectory);
                _actions.SendError(
                    id,
                    "PreexistingRebuildErrors",
                    "the copy was refused for pre-existing rebuild errors and has already been "
                    + "deleted, so there is nothing left to plan against. The count that came "
                    + "back with the refusal was 0, which does not say how many errors were "
                    + "found. Check the part in SOLIDWORKS; the run folder is kept.",
                    retryable: true);
                return;
            }

            PostStatus("planning", "Planning the reorganization...");
            string planSummary;
            try
            {
                planSummary = pipeline.Plan(runDirectory, reporter);
            }
            catch (Exception failure)
            {
                PostStatus("error", PageWords(failure));
                EndTheSessionOfAFailedPlan(pipeline, runDirectory, attachment);
                throw;
            }

            RemodelRun run = Track(runDirectory, copy.CopyPath, attachment);
            EndTheSessionNoStartCanUse(pipeline, run);
            PostStatus("ready", "Planned. Press Start to apply the plan to the copy.");

            using (JsonDocument summary = JsonDocument.Parse(planSummary))
            {
                _actions.Send("remodel.planned", id, new Dictionary<string, object?>
                {
                    { "run_dir", run.RunDirectory },
                    { "plan_summary", summary.RootElement },
                });
            }
        }
        finally
        {
            // Decision 24A: a re-attach that landed while this plan held the host was not told
            // then. It is asked about now, of whichever plan is on screen - the one just
            // recorded, or the earlier one if this plan was refused.
            FreeTheHost();
        }
    }

    /// <summary>
    /// 004 T173 (default taken 2026-09-26, the owner may revise; research R13.4): planning again
    /// while an earlier plan waits for Start. The earlier plan is the latest run while it is
    /// planned and waiting - not started, not finished, its copy not discarded - whatever marks it
    /// already carries.
    ///
    /// Its session is closed through the pipeline's close (`POST /remodel/close`,
    /// <c>discard_copy: false</c>, which reaches the bridge's end-of-session routine) when its
    /// attachment is the one listening now - Start's and Discard's predicate - and nothing is
    /// sent when it is gone, since that session went with its attachment. The close is unsaved:
    /// the copy stays in <c>copy/</c>, the folder stays whole and <c>plan.json</c> stays
    /// <c>planned</c>. Then the plan is marked lost in this host's record and the page is told
    /// once, with <see cref="PlanClosedMessage"/>.
    ///
    /// A close the bridge could not answer - refused as <c>BridgeUnavailable</c>, or failed with no
    /// named refusal at all - refuses the new plan with <c>BridgeUnavailable</c> and leaves the
    /// earlier plan as it was (lane D's default, 2026-09-27); since owner decision 159A, on review, so does
    /// a close that never reached the bridge (<see cref="CloseNotAnsweredClasses"/>), with its own class, and
    /// each in <see cref="EarlierPlanNotClosedMessage"/>. A close that answered with what it
    /// left - any other named refusal - lets the new plan go ahead: the routine clears the session
    /// whatever it left, and what it left reaches the page as T167's one status error through
    /// <c>ToolServiceOptions.RemodelSessionEnded</c>, which is told every ending, so nothing is
    /// posted here for it.
    /// </summary>
    /// <returns>False when the new plan was refused and has been answered.</returns>
    private bool EndTheWaitingPlan(string? id, IRemodelPipeline pipeline, string? attachment)
    {
        RemodelRun? waiting = LatestRun;
        if (waiting != null && waiting.Phase == RemodelRunPhase.Finished && !waiting.CopyDiscarded)
        {
            return EndTheSessionARunLeft(id, pipeline, waiting, attachment);
        }

        if (waiting == null || waiting.Phase != RemodelRunPhase.Planned || waiting.CopyDiscarded)
        {
            return true;
        }

        if (HoldsItsSession(waiting, attachment)
            && CloseSession(pipeline, waiting.RunDirectory, out Exception? notAnswered) == CloseAnswer.NotAnswered)
        {
            // Owner decision 159A (004 research R19): the close's failure, which can name the bridge's pipe, goes to
            // the log. On review (the mutation review's M3): whoever did not answer - the bridge, its refusal carried
            // by the backend, or a close that never reached it - the earlier plan is left as it was, and the tab says
            // so in one sentence; the class the close was refused with is kept, and any other failure is
            // `BridgeUnavailable`. Pressing again sends the close again.
            Log("remodel.plan, the earlier plan's close", notAnswered!);
            string errorClass = notAnswered is RemodelRefusal refusal ? refusal.ErrorClass : BridgeUnavailableClass;
            _actions.SendError(id, errorClass, EarlierPlanNotClosedMessage, retryable: true);
            return false;
        }

        // Closed, or answered with what it left (see the remarks), or nothing to close.
        waiting.MarkClosedByPlanAgain();
        TellPlanLost(waiting);
        return true;
    }

    /// <summary>
    /// Owner decision 159A, on the final review (S2): a finished run whose close was not answered - its backend gone
    /// mid-run, so the close was never sent - may still hold its session on the bridge: the copy open, the settings
    /// changed. One bridge holds one session, and since protocol 1.5 a close names its run, so no other run's close ends
    /// it: the next plan's open was refused <c>run_in_progress</c>, its clean-up close was refused as another run's, and
    /// every later press did the same. So before the next plan asks for anything, that session is closed, naming the run
    /// that holds it, when its attachment is the one listening now (<see cref="HoldsItsSession"/>). A close the bridge
    /// answered, with what it left or none of the run's left to end, marks the run's session ended; one not answered
    /// refuses the new plan, retryable, in <see cref="EarlierRunNotClosedMessage"/>, the close's class kept and its
    /// failure in the log, and pressing again asks the close again.
    /// </summary>
    /// <returns>False when the new plan was refused and has been answered.</returns>
    private bool EndTheSessionARunLeft(string? id, IRemodelPipeline pipeline, RemodelRun run, string? attachment)
    {
        if (!HoldsItsSession(run, attachment))
        {
            return true;
        }

        if (CloseSession(pipeline, run.RunDirectory, out Exception? notAnswered) == CloseAnswer.NotAnswered)
        {
            Log("remodel.plan, the earlier run's close", notAnswered!);
            string errorClass = notAnswered is RemodelRefusal refusal ? refusal.ErrorClass : BridgeUnavailableClass;
            _actions.SendError(id, errorClass, EarlierRunNotClosedMessage, retryable: true);
            return false;
        }

        run.MarkSessionEnded();
        return true;
    }

    /// <summary>What the bridge made of one close of a plan's session (004 T173's reading, shared).</summary>
    private enum CloseAnswer
    {
        /// <summary>The close returned: the session is over, and everything was put back.</summary>
        Closed,

        /// <summary>
        /// A named refusal other than those of <see cref="CloseNotAnsweredClasses"/>: after it the bridge holds no session
        /// of this run. Either its end-of-session routine ran, which clears the session whatever it left - what it left
        /// reaching the page as T167's one status error through <c>ToolServiceOptions.RemodelSessionEnded</c> - or there
        /// was none of this run's to end: no session at all (<c>target_mismatch</c>), or, since protocol 1.5, another
        /// run's (<c>session_mismatch</c>, which the backend answers as <c>RunFolderFailed</c>), left as it was and told
        /// nothing (owner decision 159A, on the final review: S2). Every reader acts on that alone: this run holds no
        /// session.
        /// </summary>
        AnsweredWithWhatItLeft,

        /// <summary>
        /// <c>BridgeUnavailable</c>, a close that never reached the bridge's routine
        /// (<see cref="CloseNotAnsweredClasses"/>), or a failure with no named refusal at all: the bridge
        /// may still hold the session.
        /// </summary>
        NotAnswered,
    }

    /// <summary>
    /// The classes a close is refused with when the bridge's end-of-session routine may not have run: the
    /// bridge did not answer (<c>BridgeUnavailable</c>); and, owner decision 159A on review (the mutation
    /// review's M6, older than 159A), the close never reached it - the add-in's client gave up on the review
    /// backend after its 30 seconds while the backend waited 60 for the bridge, or no backend was running
    /// (<c>BackendUnavailable</c>), the backend's answer could not be read (<c>HttpError</c>,
    /// <c>BadResponse</c>), or the backend refused the request before asking the bridge (<c>InvalidRunDir</c>,
    /// <c>InvalidRequest</c>). Any other named refusal is the routine's answer with what it left.
    /// </summary>
    private static readonly HashSet<string> CloseNotAnsweredClasses = new HashSet<string>(StringComparer.Ordinal)
    {
        BridgeUnavailableClass,
        "BackendUnavailable",
        "HttpError",
        "BadResponse",
        "InvalidRunDir",
        "InvalidRequest",
    };

    /// <summary>
    /// One close of the session the bridge holds for <paramref name="runDirectory"/>'s plan, through
    /// the pipeline's close (<c>POST /remodel/close</c>, <c>discard_copy: false</c>, so the bridge's
    /// end-of-session routine: unsaved, deleting nothing), read the way planning again reads it
    /// (004 T173). It never throws; <paramref name="notAnswered"/> is the failure when the bridge
    /// could not answer.
    /// </summary>
    private static CloseAnswer CloseSession(
        IRemodelPipeline pipeline, string runDirectory, out Exception? notAnswered)
    {
        notAnswered = null;
        try
        {
            pipeline.CloseCopy(runDirectory);
            return CloseAnswer.Closed;
        }
        catch (RemodelRefusal refusal) when (!CloseNotAnsweredClasses.Contains(refusal.ErrorClass))
        {
            return CloseAnswer.AnsweredWithWhatItLeft;
        }
        catch (Exception failure)
        {
            notAnswered = failure;
            return CloseAnswer.NotAnswered;
        }
    }

    /// <summary>
    /// 004 T175 (default taken 2026-09-27, the owner may revise; research R14.1): a plan that asked
    /// the pipeline for the open and ends without recording a run - the open refused or failed, or
    /// the plan step after it failed - ends the session that open may have left, before the page is
    /// answered, through <see cref="CloseSession"/>: unsaved, the copy and the run folder kept as
    /// the evidence. Once the open was asked for, the host cannot tell a refused open from one whose
    /// reply was lost or whose backend steps after it failed; any session the bridge holds then is
    /// one nothing else this host sends will end - planning again closed the waiting plan's first
    /// (004 T173), and in this build no run has started - and a close with no session is answered
    /// with no SOLIDWORKS call. Whatever the close does, the page is told the
    /// plan's own failure: a close that fails is not this plan's answer. Since 004 T258, an
    /// unanswered close keeps its run folder and attachment for the next plan to retry before
    /// probing or copying anything, without inventing a successful RemodelRun.
    /// </summary>
    private void EndTheSessionOfAFailedPlan(IRemodelPipeline pipeline, string runDirectory, string? attachment)
    {
        // The service hold prevents ordinary replacement during Plan, but never send this run's
        // cleanup to a different dispatcher if an explicit detach still replaced the attachment.
        if (!SameAttachment(attachment, _options.ToolServiceAttachment()))
        {
            return;
        }

        lock (_attemptLock)
        {
            // Owner decision 159A (004 research R22.14): the bridge told this attempt's end already - its session is
            // over, so there is nothing to close and nothing to leave.
            if (_attemptEnded && SamePath(_attemptRun, runDirectory))
            {
                return;
            }

            _failedPlanToClose = Tuple.Create(runDirectory, attachment);
        }

        if (CloseSession(pipeline, runDirectory, out Exception? notAnswered) == CloseAnswer.NotAnswered)
        {
            Log("remodel.plan, the failed plan's close", notAnswered!);
        }
        else
        {
            _failedPlanToClose = null;
        }
    }

    /// <summary>
    /// 004 T258: retry an unanswered failed-plan cleanup before a new probe, naming exactly its
    /// original run. A replacement attachment has no session of that attempt to close. Backend
    /// availability and run-root validation remain the pipeline's: a close refused before reaching
    /// the bridge leaves the identity for another attempt and refuses the new plan retryably.
    /// </summary>
    private bool EndTheFailedPlan(string? id, IRemodelPipeline pipeline, string? attachment)
    {
        Tuple<string, string?>? failed = _failedPlanToClose;
        if (failed == null)
        {
            return true;
        }

        if (!SameAttachment(failed.Item2, attachment))
        {
            _failedPlanToClose = null;
            return true;
        }

        if (CloseSession(pipeline, failed.Item1, out Exception? notAnswered) == CloseAnswer.NotAnswered)
        {
            Log("remodel.plan, the failed plan's close", notAnswered!);
            string errorClass = notAnswered is RemodelRefusal refusal ? refusal.ErrorClass : BridgeUnavailableClass;
            _actions.SendError(id, errorClass, FailedPlanNotClosedMessage, retryable: true);
            return false;
        }

        _failedPlanToClose = null;
        return true;
    }

    /// <summary>
    /// Owner decision 159A (004 research R22): the cleanup a settings restart that moves the run root asks for before it
    /// stops the backend in force (<c>ReviewHostOptions.EndRemodelSessionsLeftUnder</c>). Every session this host can have
    /// left on the bridge - a failed plan's whose close was not answered (004 T258), a plan waiting for Start that still
    /// holds its session, and a finished run's whose close was not answered - is closed now, through the pipeline's close
    /// (<see cref="CloseSession"/>), naming its exact run, while the backend in force is the one that takes its run folder:
    /// the restarted backend refuses a folder outside its run root before the bridge, so after the restart no close of it
    /// could ever be sent, and every plan would ask again. Only what lies under <paramref name="runRoot"/>, the run root
    /// leaving, and only on the attachment listening now (<see cref="SameAttachment"/>, <see cref="HoldsItsSession"/>): a
    /// session of an attachment gone went with it, and a close is never sent to a replacement. The tool service is held
    /// for the closes, as a plan holds it, so no follow takes the bridge down under them; with none listening there is no
    /// session to close.
    ///
    /// A close answered - closed, or answered with what it left - ends the leftover as planning again ends it: a failed
    /// plan's record is let go, and a run is marked <see cref="RemodelRun.ClosedForRunRoot"/>, so no close is sent for it
    /// again, and a plan so closed is told lost in <see cref="PlanClosedForRunRootMessage"/>'s words. A close not answered
    /// leaves the leftover as it was, its failure in the log, and answers false at once, so the restart waits.
    ///
    /// 004 research R22.10, on review: a run whose copy was discarded is closed too while it holds its session - Discard
    /// deletes the copy folder whatever its own close answered - and a second close of one that already ended is answered
    /// with no SOLIDWORKS call. A run's close is marked sent (<see cref="RemodelRun.CloseSentFor"/>) before it goes,
    /// since the bridge tells its end (<see cref="SessionEnded(RemodelSessionEnd)"/>) before the close is answered.
    ///
    /// Called under the restart's lock, after the review host has read this host free: a plan or a run begins only through
    /// that lock (<see cref="RemodelHostOptions.BeginRun"/>), so none begins while this runs.
    /// </summary>
    /// <param name="runRoot">The run root in force, which the restart would move.</param>
    /// <returns>True when nothing under it is left holding a session; false when a close was not answered.</returns>
    public bool EndTheSessionsLeftUnder(string runRoot)
    {
        IRemodelPipeline? pipeline = _options.Pipeline;
        if (pipeline == null)
        {
            return true;
        }

        IDisposable? hold = _options.HoldToolService();
        if (hold == null)
        {
            return true;
        }

        try
        {
            string? attachment = _options.ToolServiceAttachment();
            Tuple<string, string?>? failed = _failedPlanToClose;
            if (FailedPlanLeftUnder(failed, attachment, runRoot))
            {
                if (!ClosedBeforeTheRunRootMoves(pipeline, failed!.Item1))
                {
                    return false;
                }

                _failedPlanToClose = null;
            }

            RemodelRun? left = LatestRun;
            if (RunLeftUnder(left, attachment, runRoot))
            {
                left!.MarkCloseSentFor(RemodelCloseCause.RunRoot);
                if (!ClosedBeforeTheRunRootMoves(pipeline, left.RunDirectory))
                {
                    return false;
                }

                left.MarkSessionClosedFor(RemodelCloseCause.RunRoot);
                AnnounceLostPlan();
            }

            return true;
        }
        finally
        {
            try
            {
                hold.Dispose();
            }
            catch (Exception)
            {
                // The hold's own failure: the closes are made, and the gate's own holds never fail.
            }
        }
    }

    /// <summary>
    /// Owner decision 159A (004 research R22.12, Codex's third review): whether this host still holds a session on the
    /// bridge under <paramref name="runRoot"/> - what <see cref="EndTheSessionsLeftUnder"/> would close, read now and
    /// closing nothing, holding nothing and asking no backend: a failed plan's whose close was not answered, or the latest
    /// run while it holds its session, on the attachment listening now. The review host reads it when a restart waits
    /// to move the run root and the backend does not answer, so its words say what holds the restart now - a close that
    /// ended late, a re-attach or a newer save change the answer by themselves. No pipeline is none.
    /// </summary>
    public bool HoldsASessionLeftUnder(string runRoot)
    {
        if (_options.Pipeline == null)
        {
            return false;
        }

        string? attachment = _options.ToolServiceAttachment();
        return FailedPlanLeftUnder(_failedPlanToClose, attachment, runRoot) || RunLeftUnder(LatestRun, attachment, runRoot);
    }

    /// <summary>A failed plan whose close was not answered, made on <paramref name="attachment"/>, under <paramref name="runRoot"/>.</summary>
    private bool FailedPlanLeftUnder(Tuple<string, string?>? failed, string? attachment, string runRoot) =>
        failed != null
        && SameAttachment(failed.Item2, attachment)
        && RunFolders.IsUnder(failed.Item1, runRoot, _options.RunRootProbe);

    /// <summary>A run that still holds its session on <paramref name="attachment"/> (<see cref="HoldsItsSession"/>), under <paramref name="runRoot"/>.</summary>
    private bool RunLeftUnder(RemodelRun? run, string? attachment, string runRoot) =>
        run != null
        && HoldsItsSession(run, attachment)
        && RunFolders.IsUnder(run.RunDirectory, runRoot, _options.RunRootProbe);

    /// <summary>
    /// One close of <see cref="EndTheSessionsLeftUnder"/>'s: whether the bridge answered it, its failure in the log when not.
    /// </summary>
    private bool ClosedBeforeTheRunRootMoves(IRemodelPipeline pipeline, string runDirectory)
    {
        if (CloseSession(pipeline, runDirectory, out Exception? notAnswered) != CloseAnswer.NotAnswered)
        {
            return true;
        }

        Log("a restart that moves the run root, the earlier copy's close", notAnswered!);
        return false;
    }

    /// <summary>
    /// 004 T176 (default taken 2026-09-27, the owner may revise; research R14.2): while Start is
    /// switched off, no Start can use a plan's session, and holding it would keep the engineer's
    /// four application-wide settings changed for as long as the plan waits - <c>CommandInProgress</c>
    /// set and the save-with-errors warning off, over the engineer's own part. So the session is
    /// ended as soon as the plan is recorded, before the page is told the plan was made, through
    /// <see cref="CloseSession"/>: the copy stays in <c>copy/</c> and <c>plan.json</c> stays
    /// <c>planned</c>. A close the bridge answered, with or without something left, marks the plan
    /// <see cref="RemodelRun.SessionClosedAtPlan"/>, so no close is sent for it again; one it could
    /// not answer leaves the plan holding its session, so Discard, planning again, a re-attach or an
    /// unload still end it. With Start switched on the plan keeps its session for Start.
    /// </summary>
    private void EndTheSessionNoStartCanUse(IRemodelPipeline pipeline, RemodelRun run)
    {
        if (StartValidated)
        {
            return;
        }

        if (CloseSession(pipeline, run.RunDirectory, out _) != CloseAnswer.NotAnswered)
        {
            run.MarkSessionClosedAtPlan();
        }
    }

    /// <summary>
    /// 004 T173: whether <paramref name="documentPath"/> is one of the re-modeler's own copies - a
    /// file in a <c>copy</c> folder whose run folder is a direct child of a run root in force this
    /// session, by <see cref="RemodelCopy.RunDirectoryOf"/>'s rule, canonical and case-insensitive (lane
    /// D's default, 2026-09-27). Every run root in force this session, not only the one in force now, so
    /// a copy made under one a settings save has since moved is still a copy (owner decision 154A, the
    /// reviews' finding F6). A folder merely named <c>copy</c> anywhere else is not one, and a path that
    /// cannot be read as one is not one either: this check refuses, it never guesses.
    /// </summary>
    private bool IsRemodelCopy(string documentPath)
    {
        string runDirectory;
        try
        {
            runDirectory = RemodelCopy.RunDirectoryOf(documentPath);
        }
        catch (Exception error) when (error is Extractor.Guard.MutatingCallError
            || error is Extractor.Bridge.RemodelCommandError
            || error is ArgumentException
            || error is NotSupportedException
            || error is PathTooLongException)
        {
            // Not in a copy folder (the rule's refusal), or not a path that canonicalizes.
            return false;
        }

        string? parent = Path.GetDirectoryName(
            runDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
        return parent != null && _options.RunRootsInForce().Any(runRoot => IsTheRunRoot(parent, runRoot));
    }

    /// <summary>Whether <paramref name="folder"/> is <paramref name="runRoot"/>, canonical and case-insensitive.</summary>
    private static bool IsTheRunRoot(string folder, string runRoot)
    {
        string root;
        try
        {
            root = Path.GetFullPath(runRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        }
        catch (Exception error) when (error is ArgumentException
            || error is NotSupportedException
            || error is PathTooLongException)
        {
            return false;
        }

        return string.Equals(
            folder.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar), root, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// The scope half of the refusals, in the contract's order: the three the bridge raises
    /// before any signal comes back, then the pure gate's verdict, then any signal that could
    /// not be read at all.
    ///
    /// A null signal is <b>not</b> a pass (data-model.md section 4.1). Every failing reason is
    /// named in the one message, because a refusal that named one of two sends the engineer
    /// back twice.
    /// </summary>
    private bool ScopeAllowsARun(string? id, RemodelScopeReading scope)
    {
        ScopeSignals signals = scope.Signals;

        // Owner decision 155A: one sentence per class, the tab's own, whoever refused (PageWords). The
        // bridge as built never reaches these two: its probe refuses `source_dirty` and `external_refs`
        // before it answers a dirty save flag or a count of references.
        if (signals.SaveFlagDirty == true)
        {
            _actions.SendError(id, "DocumentDirty", DocumentDirtyMessage, retryable: true);
            return false;
        }

        if (signals.ExternalReferenceCount > 0)
        {
            _actions.SendError(id, "ExternalReferences", ExternalReferencesMessage, retryable: false);
            return false;
        }

        var refusals = new List<string>(scope.Refusals);

        // Every unreadable signal the host itself reads is reported as `signal_unresolved`,
        // spelled the way `bridge/remodel_client.py` spells it, because a token that differs by
        // an underscore is a refusal that maps to no class on the Python side.
        if (signals.SaveFlagDirty == null)
        {
            // U26 (default taken 2026-09-28, the owner may revise): the probe answers null when
            // the source is read-only and SOLIDWORKS would not report its unsaved changes, so the
            // refusal says which option hides them and the two ways past it.
            refusals.Add(
                "signal_unresolved: save_flag_dirty could not be read or cannot be trusted - SOLIDWORKS "
                + "does not report unsaved changes to a part open read-only while "
                + "\"Don't prompt to save read-only referenced documents\" is selected (Tools > Options > "
                + "System Options > External References); turn that option off, or check the part out, "
                + "then press Remodel again");
        }

        if (signals.ReadOnly == null)
        {
            refusals.Add("signal_unresolved: read_only could not be read");
        }

        if (signals.ExternalReferenceCount == null)
        {
            refusals.Add("signal_unresolved: external_reference_count could not be read");
        }

        if (refusals.Count == 0)
        {
            return true;
        }

        _actions.SendError(
            id,
            "ScopeRefused",
            "the re-modeler will not run on this part: " + string.Join("; ", refusals) + ".",
            retryable: false);
        return false;
    }

    // ---- remodel.start / remodel.stop ----------------------------------------------------

    private void Start(string? id, JsonElement payload)
    {
        // Owner decision 154A: first, as a plan is refused - the run hands its folder to the backend and the
        // bridge again.
        string judged = _options.RunRoot();
        if (RunRootRefused(id, judged, "the plan was not applied"))
        {
            return;
        }

        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id);
            return;
        }

        if (_busy)
        {
            SendRunInProgress(id);
            return;
        }

        if (run.CopyDiscarded || !CopyExists(run))
        {
            _actions.SendError(
                id,
                "CopyDiscarded",
                "this run's copy has been discarded, so there is nothing left to reorganize. "
                + "The plan, the change list and the report are still in the run folder.",
                retryable: false);
            return;
        }

        // The state comes off the disk, not out of this host's memory: a run interrupted
        // mid-apply left `applying` in `plan.json`, and the tree it left behind was never
        // re-verified. Replaying changes onto it is exactly the wrong risk.
        string? state = StateOf(run.RunDirectory);
        if (!string.Equals(state, PlannedState, StringComparison.Ordinal))
        {
            _actions.SendError(
                id,
                "ResumeRefused",
                $"this run is '{state ?? "unreadable"}' rather than 'planned', and a run is "
                + "never resumed: the copy it left behind was not re-verified. Press Remodel "
                + "again to start a fresh run.",
                retryable: false);
            return;
        }

        // 004 T172: Start is switched off until the blocking probes pass. After ResumeRefused, so
        // a run that can never be resumed says so first, and before SessionLost, so the engineer
        // is never sent to plan again for a Start this build would refuse anyway. Before any
        // pipeline, backend or bridge call, and with nothing written.
        if (!StartValidated)
        {
            _actions.SendError(id, "StartNotValidated", StartNotValidatedMessage, retryable: false);
            return;
        }

        // Decision 22A: the plan's bridge session lives on the attachment the plan was made on
        // and does not survive a re-attach, so a run whose attachment is not the one listening
        // now is refused here, before `remodel.started` and before any call that could change
        // anything. Ahead of the seat check on purpose: mid-restart the seat reads as still
        // being checked, and asking the engineer to wait would only earn this answer next time.
        // 004 T173: a plan planning again closed is lost the same way, in its own words.
        string? lost = LostSessionWords(run);
        if (lost != null)
        {
            _actions.SendError(id, "SessionLost", lost, retryable: false);
            return;
        }

        RemodelAvailability availability = _options.RemodelAvailability();
        if (availability != RemodelAvailability.Available)
        {
            SendUnavailable(id, availability);
            return;
        }

        IRemodelPipeline? pipeline = _options.Pipeline;
        if (pipeline == null)
        {
            _actions.SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so the plan cannot be "
                + "applied.",
                retryable: true);
            return;
        }

        // Owner decision 145A: a run begins as a plan does (Plan, above), after every refusal that
        // needs no call and before `remodel.started`.
        if (!BeganRun(id, StartAfterRestartMessage))
        {
            return;
        }

        // From here the run holds the host. Whatever ends Start before the run is handed to its
        // scheduler - the refusal below, or anything that throws - frees it again: a host left busy
        // would hold back every settings restart, and every new review with it, until SOLIDWORKS
        // restarts (owner decision 145A, found on review).
        RemodelRunPhase phaseBefore = run.Phase;
        bool started = false;
        bool handedOver = false;
        try
        {
            // The reviews of decision 154A, N8 and finding F6: the gate can make a waiting settings restart,
            // which can bring another run root into force - judged again - and the backend makes runs only under
            // the one it was started with, so a plan made under one a save has since moved is not applied.
            string? runRoot = RunRootToUse(id, judged, "the plan was not applied");
            if (runRoot == null)
            {
                return;
            }

            if (!RunFolders.IsUnder(run.RunDirectory, runRoot, _options.RunRootProbe))
            {
                _actions.SendError(id, "RunRootChanged", StartRunRootChangedMessage, retryable: false);
                return;
            }

            // Owner decision 152A, on the Codex review (X2): the run holds the tool service until its
            // session is closed (Execute), taken before the session is read again below. None
            // listening to hold means the plan's attachment is gone or going, and its session with it.
            // After the run root (merged with 154A, 2026-10-21), as at a plan: the run root, and the
            // plan's folder under it, before anything is asked of the tool service.
            if (!HoldTheToolService())
            {
                _actions.SendError(id, "SessionLost", LostSessionWords(run) ?? SessionLostMessage, retryable: false);
                return;
            }

            // The gate may have waited through a settings restart - seconds in which the host was
            // not busy, so the tool service was free to re-attach, or a teardown to end the plan's
            // session. Read again now the host is busy, which a re-attach of the service's own asks
            // before it moves: a run never starts on a session that went while the gate waited
            // (decision 22A).
            lost = LostSessionWords(run);
            if (lost != null)
            {
                _actions.SendError(id, "SessionLost", lost, retryable: false);
                return;
            }

            run.Phase = RemodelRunPhase.Running;
            _active = run;

            // The reply goes first, so the page has the chat id before the first `status` or
            // `remodel.change` arrives on it.
            _actions.Send("remodel.started", id, new Dictionary<string, object?>
            {
                { "chat_id", run.RunId },
            });
            started = true;

            _options.Schedule(() => Execute(pipeline, run));
            handedOver = true;
        }
        catch (Exception failure) when (started)
        {
            // The page was told the run began, and none is coming: it is told the run is over by
            // the status a run's end posts, and the failure is answered as any failure is - in this
            // tab's words, its message logged (owner decision 159A). The run is let go of first, under
            // the lock that frees the host (159A, on review), so the stop when the copy goes away is
            // never told after that last word.
            LetGoOfARunNeverHandedOn(run);
            PostStatus("error", PageWords(failure));
            throw;
        }
        finally
        {
            if (!handedOver)
            {
                // Nothing runs: what Start set is undone, the plan stays startable, and nothing is
                // left in flight for Stop.
                run.Phase = phaseBefore;
                LetGoOfARunNeverHandedOn(run);
                // Decision 24A: a re-attach or a teardown that took the plan's session while Start
                // held the host was not announced then; it is now, as the end of a plan announces it.
                FreeTheHost();
            }
        }
    }

    /// <summary>
    /// Phases B to D, to completion, off the message thread.
    ///
    /// Never throws into the scheduler: a faulted background task in a SOLIDWORKS add-in is an
    /// unobserved exception nobody sees. A failure is a `status {stage: "error"}` and an
    /// `error` message, and the run ends `failed`.
    ///
    /// Owner decision 155A (004 research R18; feature 011 research R12.9 item 4): the page ends its
    /// running state - and offers Open copy and Discard copy again - on a `status` of `ready` or
    /// `error`, so none is posted while the run holds the host. What the ending says before the host
    /// is free - the failure caught here, the pipeline's own error, T167's words of a close that left
    /// something - is held (<see cref="HoldUntilTheHostIsFree"/>) and told once the session is closed
    /// and the host freed, in the order it was made, then the run's last word, then the answer to every
    /// Stop that reached the run (owner decision 159A).
    /// </summary>
    private void Execute(IRemodelPipeline pipeline, RemodelRun run)
    {
        RemodelRunOutcome outcome;
        string? closeProblem = null;
        List<Action> held;
        List<string?> stops;
        try
        {
            var reporter = new RunReporter(this, run);
            reporter.Status("judging", RunningThePlanMessage);
            outcome = pipeline.Run(run.RunDirectory, reporter);
        }
        catch (RemodelRefusal refusal)
        {
            // Unsolicited: `remodel.started` was answered before the run began, so there is no
            // message left to reply to. The class still travels, for the reason it does on the
            // message thread.
            HoldUntilTheHostIsFree(() =>
            {
                PostStatus("error", PageWords(refusal));
                SendRefusal(null, refusal, "the run");
            });
            outcome = new RemodelRunOutcome("failed", 0);
        }
        catch (Exception failure)
        {
            // Owner decision 159A (004 research R19): in this tab's words, its message logged.
            Log("the run", failure);
            HoldUntilTheHostIsFree(() =>
            {
                PostStatus("error", UnexpectedFailureMessage);
                _actions.SendError(null, "HostError", UnexpectedFailureMessage, retryable: false);
            });
            outcome = new RemodelRunOutcome("failed", 0);
        }
        finally
        {
            if (HoldsItsSession(run, _options.ToolServiceAttachment()))
            {
                CloseAnswer closed = CloseSession(pipeline, run.RunDirectory, out Exception? notAnswered);
                if (closed != CloseAnswer.NotAnswered)
                {
                    run.MarkSessionEnded();
                }
                else
                {
                    // Owner decision 159A: the close's failure, which ended this sentence, goes to the log.
                    Log("the run's close", notAnswered!);
                    closeProblem = RunCloseNotAnsweredMessage;
                }
            }

            // Owner decision 152A, on the Codex review (X2): held until the run's session is closed,
            // above, on the bridge it ran on - and let go before the host is free, since this is the
            // run's own thread (on review, N4): a plan pressed the moment the host is free takes a hold
            // of its own, which letting go after would let go of.
            LetGoOfTheToolService();
            held = FreeTheHostFromTheRun(run, out stops);
        }

        foreach (Action post in held)
        {
            post();
        }

        if (closeProblem != null)
        {
            PostStatus("error", closeProblem);
        }
        else if (outcome.State == "failed")
        {
            PostStatus("error", "The run ended without saving the copy. The report says why.");
        }
        else
        {
            PostStatus(
                "ready",
                $"The run ended '{outcome.State}'. Open the report for the change list, the "
                + "grade and the geometry comparison.");
        }

        // The stop is answered when the executor has finalized, not when the flag was set:
        // `changes_applied` is not knowable until the change in flight has landed or been
        // inverted. Every Stop that reached this run, each once, taken as the host was freed (owner
        // decision 159A); a run stopped only because its copy went away is answered unasked, as before.
        var stopped = new Dictionary<string, object?>
        {
            { "changes_applied", outcome.ChangesApplied },
        };
        foreach (string? stopId in stops)
        {
            _actions.Send("remodel.stopped", stopId, stopped);
        }

        if (stops.Count == 0 && run.StopRequested)
        {
            _actions.Send("remodel.stopped", null, stopped);
        }
    }

    /// <summary>
    /// The words Start refuses a plan whose bridge session is gone with (`SessionLost`), or null
    /// while the plan holds it: <see cref="PlanClosedMessage"/> for one planning again closed (004
    /// T173), <see cref="PlanClosedForRunRootMessage"/> for one closed before a restart moved the run root
    /// (owner decision 159A, 004 research R22), and <see cref="SessionLostMessage"/> for one whose session a teardown ended or whose
    /// attachment is not the one listening now (decision 22A). One reading for Start's check
    /// before the restart gate and its check again once the host is busy (owner decision 145A).
    /// </summary>
    private string? LostSessionWords(RemodelRun run)
    {
        if (run.ClosedByPlanAgain)
        {
            return PlanClosedMessage;
        }

        if (run.ClosedForRunRoot)
        {
            return PlanClosedForRunRootMessage;
        }

        return run.SessionEnded || !SameAttachment(run.ToolServiceAttachment, _options.ToolServiceAttachment())
            ? SessionLostMessage
            : null;
    }

    /// <summary>
    /// Whether the attachment a plan was made on is the one listening now. Ordinal, because a
    /// pipe name is minted, never typed. A missing or blank name on either side is never a
    /// match - not even with another missing one - because an unknown attachment is not known
    /// to be the same one (constitution Principle I).
    /// </summary>
    private static bool SameAttachment(string? planned, string? now) =>
        !string.IsNullOrWhiteSpace(planned)
        && !string.IsNullOrWhiteSpace(now)
        && string.Equals(planned, now, StringComparison.Ordinal);

    /// <summary>
    /// Whether <paramref name="run"/>'s bridge session can still be on the bridge listening now,
    /// so that a `remodel.close` - which named no run and closed whatever session the bridge held,
    /// until owner decision 159A had it name its run and the bridge refuse another run's - would
    /// reach its session and nobody else's: made on the attachment listening now
    /// (<see cref="SameAttachment"/>, T168), not closed by planning again (004 T173) and not closed
    /// by the host at the plan while Start is switched off (004 T176), and not ended since then
    /// (T180). One predicate for Discard, planning again, finished-run close and copy preservation.
    /// </summary>
    private static bool HoldsItsSession(RemodelRun run, string? attachmentNow) =>
        !run.ClosedByPlanAgain
        && !run.SessionClosedAtPlan
        && !run.SessionEnded
        && SameAttachment(run.ToolServiceAttachment, attachmentNow);

    /// <summary>
    /// Whether <paramref name="run"/> is a plan that can no longer be started (decision 24A):
    /// planned and waiting for Start - not started, not finished, its copy not discarded - and
    /// made on an attachment that is not the one listening now, none included, by Start's own
    /// predicate, <see cref="SameAttachment"/>. The attachment decides, never the document, so a
    /// re-attach back to the same part is a loss and a configuration switch, which re-attaches
    /// nothing, is not.
    ///
    /// One rule for the two ways the page hears of it: the notice
    /// (<see cref="AnnounceLostPlan"/>) and `init.latest_run.plan_lost`, which a page that loads
    /// again starts from (<see cref="SendInit"/>; decision 24A, amended on review).
    ///
    /// Owner decision 159A (004 research R19; 002 research 152A's owner question 3): a plan this host
    /// closed at the plan, while Start is switched off (004 T176), holds no session for a re-attach or
    /// a teardown to take, and no Start can use it in this build either way, so neither makes it lost -
    /// the tool service following the copy the plan's close left active included, which was told as
    /// SOLIDWORKS switching documents. Planning again, which sets such a plan aside, still does.
    ///
    /// Owner decision 162A (004 research R23): nor is a plan whose session the engineer's own Discard closed
    /// (<see cref="RemodelRun.ClosedFor"/>), though the bridge tells that end before the copy is marked discarded, and
    /// though the folder could not be deleted: the Discard answer is the word. A teardown's end meanwhile is a re-attach's.
    /// </summary>
    private bool IsLostPlan(RemodelRun? run) =>
        run != null
        && run.Phase == RemodelRunPhase.Planned
        && !run.CopyDiscarded
        && (run.ClosedByPlanAgain
            || (!run.SessionClosedAtPlan
                && run.ClosedFor != RemodelCloseCause.Discard
                && (run.SessionEnded
                    || !SameAttachment(run.ToolServiceAttachment, _options.ToolServiceAttachment()))));

    /// <summary>
    /// The sentence a lost plan is told with: <see cref="PlanClosedMessage"/> for one planning
    /// again closed (004 T173), whatever else it also lost, <see cref="PlanClosedForRunRootMessage"/> for one
    /// closed before a restart moved the run root (owner decision 159A, 004 research R22), and
    /// <see cref="PlanLostMessage"/> for one a re-attach took (decision 24A). One rule for the notice and for `init`.
    /// </summary>
    private static string LostMessage(RemodelRun run) =>
        run.ClosedByPlanAgain ? PlanClosedMessage
        : run.ClosedForRunRoot ? PlanClosedForRunRootMessage
        : PlanLostMessage;

    /// <summary>
    /// Tells the page that the plan on screen can no longer be started, once, as soon as this
    /// host can see it (decision 24A): `remodel.plan_lost {run_dir, message}`.
    ///
    /// The plan on screen is <see cref="LatestRun"/> - the run `init` and the last
    /// `remodel.planned` named - and it is lost by <see cref="IsLostPlan"/>.
    ///
    /// Asked on every tool-service attach and detach (<see cref="RefreshAvailability"/>) and when
    /// a plan releases the host. Never while a plan or a run holds it: a run holds the tool
    /// service, so no re-attach should land under one, and one that lands under a plan is asked
    /// about the moment that plan ends. A re-attach is two refreshes and two in a row are four,
    /// every one of them finding the attachment gone; <see cref="RemodelRun.ClaimPlanLostNotice"/>
    /// lets one notice through per plan.
    ///
    /// It changes nothing but the page. Start still refuses the plan as `SessionLost`, which
    /// stays the backstop for a Start that reaches this host before the notice reaches the page.
    /// </summary>
    private void AnnounceLostPlan()
    {
        if (_busy)
        {
            return;
        }

        RemodelRun? run = LatestRun;
        if (run == null || !IsLostPlan(run))
        {
            return;
        }

        TellPlanLost(run);
    }

    /// <summary>
    /// `remodel.plan_lost {run_dir, message}` for <paramref name="run"/>, once per plan
    /// (<see cref="RemodelRun.ClaimPlanLostNotice"/>), in <see cref="LostMessage"/>'s words. The one
    /// place the notice is posted: by <see cref="AnnounceLostPlan"/> when a refresh finds the plan
    /// lost, and by planning again, which marks it lost while it holds the host (004 T173).
    /// </summary>
    private void TellPlanLost(RemodelRun run)
    {
        if (!run.ClaimPlanLostNotice())
        {
            return;
        }

        Post("remodel.plan_lost", new Dictionary<string, object?>
        {
            { "run_dir", run.RunDirectory },
            { "message", LostMessage(run) },
        });
    }

    /// <summary>
    /// What the page's run line is told as the engineer's Stop reaches the run, in `applying`: the run goes on
    /// to its end, which follows once the host is free (owner decision 155A). Named for the page's tests (owner
    /// decision 159A); the words are as they were.
    /// </summary>
    public const string StoppingMessage =
        "Stopping: the change in flight is finished and the artifacts are finalized first.";

    /// <summary>
    /// `remodel.stop`: owner decision 159A (004 research R19; R18.7 item 4) decides it under the lock that frees
    /// the host from the run (<see cref="_endingLock"/>), and tells it under that lock, so a Stop either reaches
    /// the run - its word told before the run's end, its id answered at that end, with every other Stop of the
    /// run - or finds the host free and is answered at once, storing nothing. Read outside the lock, a Stop could
    /// read the run in flight just before the host was freed and store its id just after the end had taken it:
    /// its word was told after the run's last word, and the next run's end answered it with that run's count.
    /// </summary>
    private void Stop(string? id)
    {
        lock (_endingLock)
        {
            RemodelRun? run = _active;
            if (run != null)
            {
                _pendingStops.Add(id);
                run.RequestStop();
                run.RememberStatus("applying", StoppingMessage);
                PostStatus("applying", StoppingMessage);
                return;
            }
        }

        _actions.SendError(
            id,
            "RunNotFound",
            "no remodel run is in flight, so there is nothing to stop.",
            retryable: false);
    }

    // ---- remodel.result ------------------------------------------------------------------

    /// <summary>
    /// Read from the run folder and not from memory, so the tab answers after a restart - and
    /// so the numbers on screen are the numbers in the files the engineer can open beside them.
    ///
    /// Anything that has not been written yet is <b>null</b>, never a zero: a `grade_after`
    /// with no failures would read as a part that passed.
    /// </summary>
    private void SendResult(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id);
            return;
        }

        var open = new List<JsonDocument>();
        try
        {
            JsonDocument? plan = Load(open, run.RunDirectory, "plan.json");
            JsonDocument? grades = Load(open, run.RunDirectory, "grades.json");
            JsonDocument? geometry = Load(open, run.RunDirectory, "geometry.json");
            JsonDocument? attestation = Load(open, run.RunDirectory, "source-attestation.json");

            _actions.Send("remodel.result", id, new Dictionary<string, object?>
            {
                { "changes", ReadChanges(open, run.RunDirectory) },
                { "grade_before", Member(grades, "before") },
                { "grade_after", Member(grades, "after") },
                { "geometry", geometry?.RootElement },
                { "rebuild_list", Member(plan, "rebuild") ?? (object?)new object[0] },
                { "attestation", attestation?.RootElement },
                { "state", Text(plan, StateMember) },
            });
        }
        finally
        {
            foreach (JsonDocument document in open)
            {
                document.Dispose();
            }
        }
    }

    // ---- remodel.open_copy / remodel.discard_copy ----------------------------------------

    private void OpenCopy(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id);
            return;
        }

        // Owner decision 148A (feature 011 research R12.4; R11.8 item 9): not while a plan or a run is in
        // flight - any run's copy, not only its own - since the copy activated or opened between the run's
        // requests to the bridge would change the document SOLIDWORKS has active under the run. The page
        // offers Open copy no more than Discard copy while a run runs; this is the backstop, before
        // anything is asked of SOLIDWORKS.
        if (_busy)
        {
            _actions.SendError(id, "RunInProgress", OpenCopyWhileARunIsInProgressMessage, retryable: true);
            return;
        }

        if (run.CopyDiscarded || !CopyExists(run))
        {
            _actions.SendError(
                id,
                "CopyDiscarded",
                "this run's copy has been discarded. The plan, the change list and the report "
                + "are still in the run folder.",
                retryable: false);
            return;
        }

        IRemodelPipeline? pipeline = _options.Pipeline;
        if (pipeline == null)
        {
            _actions.SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so the copy cannot be "
                + "opened.",
                retryable: true);
            return;
        }

        try
        {
            pipeline.ActivateCopy(run.RunDirectory);
        }
        catch (RemodelRefusal refusal)
        {
            // A seat that refused by name keeps that name. `OpenFailed` is for the SOLIDWORKS
            // that would not open the file, which is a different thing to tell the engineer.
            SendRefusal(id, refusal, "remodel.open_copy");
            return;
        }
        catch (Exception failure)
        {
            // Owner decision 159A (004 research R19): the seat's sentence names the copy's full path;
            // it goes to the log.
            Log("remodel.open_copy", failure);
            _actions.SendError(id, "OpenFailed", OpenCopyFailedMessage, retryable: true);
            return;
        }

        _actions.Send("ok", id, new Dictionary<string, object?>());
    }

    /// <summary>
    /// Delete the copy and <b>keep every other artifact</b>, so "what did it propose?" stays
    /// answerable after the engineer says no.
    /// </summary>
    private void DiscardCopy(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id);
            return;
        }

        if (_busy && ReferenceEquals(_active, run))
        {
            SendRunInProgress(id);
            return;
        }

        // T168 (decision 22A): `remodel.close` named no run - the bridge closed whatever session
        // its dispatcher held, until owner decision 159A had it name its run and the bridge refuse
        // another run's - so the copy is closed only while the run still holds its session
        // on the attachment listening now (HoldsItsSession). When that attachment is gone, or
        // planning again already closed the session (004 T173), or the host closed it at the plan
        // because Start is switched off (004 T176), a close sent now would close the copy of
        // whichever plan holds the bridge. The folder is deleted either way.
        IRemodelPipeline? pipeline = HoldsItsSession(run, _options.ToolServiceAttachment())
            ? _options.Pipeline
            : null;
        if (pipeline != null)
        {
            // Owner decision 162A (004 research R23): the bridge tells the close's end before the close is answered, so
            // before the copy is marked discarded; marked the Discard's first, that end is never told as a lost plan.
            run.MarkCloseSentFor(RemodelCloseCause.Discard);
        }

        try
        {
            DeleteCopyFolder(pipeline, run.RunDirectory);
        }
        catch (Exception failure)
        {
            // Owner decision 159A (004 research R19): the disk's refusal names the copy's full path; it goes
            // to the log.
            Log("remodel.discard_copy", failure);
            _actions.SendError(id, "DiscardFailed", DiscardCopyFailedMessage, retryable: true);
            return;
        }

        run.CopyDiscarded = true;

        // `discarded` is a state transition like any other, and data-model.md section 11 has
        // `RunState` "rewritten to plan.json at every transition". It is written here because
        // this is the one transition no other component can make - the executor has finished by
        // the time the engineer presses Discard - and because `remodel.result` and
        // `init.latest_run` both read `state` straight out of `plan.json`. A host that only set
        // a field in memory would keep reporting `saved` for a run whose copy it had just
        // deleted.
        try
        {
            WritePlanState(run.RunDirectory, DiscardedState);
        }
        catch (Exception failure)
        {
            // Owner decision 159A: the disk's refusal, which ended this sentence, names plan.json's full
            // path; it goes to the log.
            Log("remodel.discard_copy, plan.json", failure);
            _actions.SendError(id, "DiscardFailed", DiscardStateNotWrittenMessage, retryable: false);
            return;
        }

        _actions.Send("ok", id, new Dictionary<string, object?>
        {
            { "kept", Kept(run.RunDirectory) },
        });
    }

    /// <summary>
    /// Rewrites `plan.json`'s `state` member and leaves every other member exactly as it was
    /// read, member for member and value for value: the rest of that file is the plan, and the
    /// plan is what "what did it propose?" is answered out of after the copy is gone.
    ///
    /// A run folder with no `plan.json` is left alone. There is no state on disk to go stale,
    /// and inventing a `plan.json` here would be this host writing a plan it did not plan.
    /// </summary>
    private static void WritePlanState(string runDirectory, string state)
    {
        string path = Path.Combine(runDirectory, "plan.json");
        if (!File.Exists(path))
        {
            return;
        }

        byte[] rewritten;
        using (JsonDocument plan = JsonDocument.Parse(File.ReadAllBytes(path)))
        {
            if (plan.RootElement.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException(
                    $"'{path}' is not a JSON object, so its state cannot be rewritten.");
            }

            using (var buffer = new MemoryStream())
            {
                using (var writer = new Utf8JsonWriter(
                    buffer, new JsonWriterOptions { Indented = true }))
                {
                    writer.WriteStartObject();
                    bool replaced = false;
                    foreach (JsonProperty member in plan.RootElement.EnumerateObject())
                    {
                        if (member.NameEquals(StateMember))
                        {
                            writer.WriteString(StateMember, state);
                            replaced = true;
                        }
                        else
                        {
                            member.WriteTo(writer);
                        }
                    }

                    if (!replaced)
                    {
                        writer.WriteString(StateMember, state);
                    }

                    writer.WriteEndObject();
                }

                rewritten = buffer.ToArray();
            }
        }

        File.WriteAllBytes(path, rewritten);
    }

    // ---- remodel.show_change -------------------------------------------------------------

    /// <summary>
    /// Show one change in SOLIDWORKS, through the persistent reference `changes.jsonl` recorded
    /// for it and through feature 003's resolver and <see cref="FeatureSelection"/>, so one
    /// resolver serves three tabs and the reply is the identical `entity.shown` payload
    /// `entity.show` already returns.
    ///
    /// A change that cannot be shown is answered, never thrown and never silently ignored: a
    /// Show that selected nothing and reported success is the behaviour FR-027 exists to
    /// prevent.
    /// </summary>
    private void ShowChange(string? id, JsonElement payload)
    {
        RemodelRun? run = FindRun(PagePayload.Text(payload, "run_dir"));
        if (run == null)
        {
            SendRunNotFound(id);
            return;
        }

        if (payload.ValueKind != JsonValueKind.Object
            || !payload.TryGetProperty("change_seq", out JsonElement value)
            || value.ValueKind != JsonValueKind.Number
            || !value.TryGetInt32(out int seq))
        {
            _actions.SendError(
                id,
                "InvalidRequest",
                "remodel.show_change needs the change's change_seq.",
                retryable: false);
            return;
        }

        var open = new List<JsonDocument>();
        try
        {
            // The last line wins: `changes.jsonl` is append-only and a change is written once
            // as `attempting` and again with its terminal status.
            JsonElement? record = ReadChanges(open, run.RunDirectory)
                .Where(change => change.TryGetProperty("seq", out JsonElement number)
                    && number.ValueKind == JsonValueKind.Number
                    && number.TryGetInt32(out int candidate)
                    && candidate == seq)
                .Select(change => (JsonElement?)change)
                .LastOrDefault();

            if (record == null)
            {
                _actions.SendEntityShown(
                    id,
                    EntityShowOutcome.NotShown(
                        -1,
                        $"change {seq} is not in this run's change list, so there is nothing to "
                        + "select.",
                        null));
                return;
            }

            string? persistRef = null;
            if (record.Value.TryGetProperty("subject", out JsonElement subject))
            {
                persistRef = PagePayload.Blank(PagePayload.Text(subject, "persist_ref"));
            }

            if (persistRef == null)
            {
                _actions.SendEntityShown(
                    id,
                    EntityShowOutcome.NotShown(
                        -1,
                        $"change {seq} recorded no persistent reference for its subject, so it "
                        + "cannot be selected. Find it in the feature tree by name.",
                        null));
                return;
            }

            // No scope and no component: the copy is a part opened on its own, so the reference
            // belongs to the document on screen and the host invents neither.
            _actions.ShowPersistRef(id, new EntityShowRequest(persistRef, null, null));
        }
        finally
        {
            foreach (JsonDocument document in open)
            {
                document.Dispose();
            }
        }
    }

    // ---- the run record and the run folder -----------------------------------------------

    /// <summary>
    /// Records the run and makes its folder the pane's latest run.
    ///
    /// Here and nowhere else, because this is the one moment a remodel folder comes into
    /// existence as something the pane is looking at: a refused plan records no run and must
    /// leave the pane pointed wherever it already was.
    /// </summary>
    private RemodelRun Track(string runDirectory, string copyPath, string? toolServiceAttachment)
    {
        var run = new RemodelRun(runDirectory, copyPath, _options.Now(), toolServiceAttachment);
        lock (_runsLock)
        {
            _runs.Add(run);
            LatestRun = run;
        }
        _options.RegisterLatestRun(runDirectory);
        return run;
    }

    /// <summary>
    /// Closes the copy without saving and deletes `copy/` and nothing else.
    ///
    /// One method for both callers - the `PreexistingRebuildErrors` refusal and
    /// `remodel.discard_copy` - because they are the same operation and a second copy of it
    /// would be a second chance to delete the wrong folder.
    ///
    /// A copy that is already gone is the ordinary case rather than a failure: the bridge's own
    /// `preexisting_rebuild_errors` handler deletes the copy and closes the document before it
    /// refuses (`contracts/bridge-remodel.md`), which reaches the host as `copy_present: false`.
    /// The close is still attempted - the host does not know which half the bridge managed -
    /// and a folder that is not there is left alone.
    ///
    /// A null <paramref name="pipeline"/> closes nothing and still deletes the folder: the
    /// add-in is not attached, or (T168, decision 22A) the run's tool-service attachment is gone
    /// and nothing of its session is left to close through another.
    /// </summary>
    private static void DeleteCopyFolder(IRemodelPipeline? pipeline, string runDirectory)
    {
        if (pipeline != null)
        {
            try
            {
                pipeline.CloseCopy(runDirectory);
            }
            catch (Exception)
            {
                // A copy that is not open, or a SOLIDWORKS that will not answer, must not stop
                // the folder being deleted: the file is what the engineer asked to be rid of.
            }
        }

        string folder = Path.Combine(runDirectory, CopyFolderName);
        if (Directory.Exists(folder))
        {
            Directory.Delete(folder, recursive: true);
        }
    }

    /// <summary>What is left in the run folder after a discard, as the reply lists it.</summary>
    private static string[] Kept(string runDirectory)
    {
        try
        {
            return Directory.GetFileSystemEntries(runDirectory)
                .Select(Path.GetFileName)
                .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
                .ToArray();
        }
        catch (Exception)
        {
            return new string[0];
        }
    }

    private bool CopyExists(RemodelRun run)
    {
        try
        {
            return File.Exists(run.CopyPath);
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>
    /// The run's state, read out of `plan.json`, or null when there is no readable answer.
    ///
    /// One reader for `init.latest_run.state`, `remodel.result.state` and the resume refusal,
    /// because three readings of the same field could disagree about a run.
    /// </summary>
    private static string? StateOf(string runDirectory)
    {
        var open = new List<JsonDocument>();
        try
        {
            return Text(Load(open, runDirectory, "plan.json"), StateMember);
        }
        finally
        {
            foreach (JsonDocument document in open)
            {
                document.Dispose();
            }
        }
    }

    /// <summary>
    /// Every `ChangeRecord` in `changes.jsonl`, in file order. A line that is not JSON is
    /// skipped rather than sent to the page as text: the page reads a record, and half a line
    /// is what a crash mid-write leaves behind.
    /// </summary>
    private static List<JsonElement> ReadChanges(List<JsonDocument> open, string runDirectory)
    {
        var changes = new List<JsonElement>();
        string path = Path.Combine(runDirectory, "changes.jsonl");
        if (!File.Exists(path))
        {
            return changes;
        }

        string[] lines;
        try
        {
            lines = File.ReadAllLines(path);
        }
        catch (Exception)
        {
            return changes;
        }

        foreach (string line in lines)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            try
            {
                JsonDocument document = JsonDocument.Parse(line);
                open.Add(document);
                changes.Add(document.RootElement);
            }
            catch (JsonException)
            {
            }
        }

        return changes;
    }

    /// <summary>One artifact, parsed, or null when it is absent or unreadable.</summary>
    private static JsonDocument? Load(List<JsonDocument> open, string runDirectory, string name)
    {
        string path;
        try
        {
            path = Path.Combine(runDirectory, name);
        }
        catch (ArgumentException)
        {
            return null;
        }

        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
            open.Add(document);
            return document;
        }
        catch (Exception)
        {
            // A half-written artifact is unknown, not empty. The page renders an absent value
            // as absent.
            return null;
        }
    }

    private static object? Member(JsonDocument? document, string name) =>
        document != null
        && document.RootElement.ValueKind == JsonValueKind.Object
        && document.RootElement.TryGetProperty(name, out JsonElement value)
            ? (object?)value
            : null;

    private static string? Text(JsonDocument? document, string name) =>
        document == null ? null : PagePayload.Text(document.RootElement, name);

    // ---- a settings restart and a plan or a run (owner decision 145A) -----------------------

    /// <summary>
    /// Marks the host busy for a plan or a run through <see cref="RemodelHostOptions.BeginRun"/>
    /// (owner decision 145A), so a settings restart that waits is made first, or the one being
    /// made is waited for, and none can begin under the plan or the run. Answers whether the host
    /// is now busy; when it is not, the press has been answered with the gate's refusal - its class,
    /// words and flag - and the host is still free, since a gate that refuses runs no step
    /// (<see cref="ReviewHost.BeginRemodelRun"/>). A gate that throws leaves the host free
    /// too, whether or not it ran the step, so one failure cannot hold every later plan, and the
    /// restart waiting on the run, back for good; the throw is the press's answer, as `Receive`
    /// gives any failure.
    /// </summary>
    /// <param name="id">The press's id, which a refusal answers.</param>
    /// <param name="restartFirst">What the page is told before the gate when a settings restart
    /// stands before the press (<see cref="RemodelHostOptions.RestartAhead"/>): the gate can wait
    /// through it for seconds, up to the backend's handshake, in which the page would otherwise say
    /// only what the press set (owner decision 145A, found on review).</param>
    private bool BeganRun(string? id, string restartFirst)
    {
        if (RestartAhead())
        {
            PostStatus("backend_starting", restartFirst);
        }

        BackendRequestException? held;
        try
        {
            held = _options.BeginRun(() => _busy = true);
        }
        catch (Exception)
        {
            _busy = false;
            throw;
        }

        if (held == null)
        {
            return true;
        }

        // Owner decision 159A (004 research R19): the gate's `BackendUnavailable` that can be pressed again - the restart
        // the press made or waited for failed, whose failure can end in the backend's log's path (decision 150A), or the
        // backend did not answer whether a turn runs - leaves the backend not restarted with the saved settings, and is
        // told in this tab's words, its own logged. The gate's other refusals - a turn, a remodel run in flight, the
        // add-in unloading - keep the words the review host writes for this tab, which name no path.
        if (string.Equals(held.ErrorClass, "BackendUnavailable", StringComparison.Ordinal) && held.Retryable)
        {
            Log("the restart gate", held.Message);
            _actions.SendError(id, held.ErrorClass, BackendNotRestartedMessage, retryable: true);
            return false;
        }

        _actions.SendError(id, held.ErrorClass, held.Message, held.Retryable);
        return false;
    }

    /// <summary>
    /// Frees the host once a plan, or a Start that did not hand its run on, is over, and tells the
    /// page of a plan lost while the host was busy, which nothing told it then (decision 24A). One
    /// copy for Plan's `finally` and Start's (owner decision 145A, third review).
    /// </summary>
    private void FreeTheHost()
    {
        // The hold first, as a run's end lets go of it (Execute): nothing held is let go once the host
        // is free for the next press.
        LetGoOfTheToolService();
        _busy = false;
        AnnounceLostPlan();
    }

    // ---- a run's ending and the host's freeing (owner decision 155A) -----------------------------

    /// <summary>
    /// Whether the page ends its running state on a `status` of <paramref name="stage"/> - and offers the
    /// copy actions again: `ready` and `error` (`remodel.js`, `showStatus`).
    /// </summary>
    private static bool EndsTheRunOnThePage(string stage) =>
        string.Equals(stage, "ready", StringComparison.Ordinal)
        || string.Equals(stage, "error", StringComparison.Ordinal);

    /// <summary>
    /// Owner decision 155A: posts <paramref name="post"/> now, or holds it while a run holds the host,
    /// for <see cref="Execute"/> to tell once the host is free - so a page that ends its running state
    /// on what it is told is never offered what the host would refuse for a run that is not over. Only
    /// a run's own ending holds anything: its executor's failure, its pipeline's error, and the words of
    /// a close made under it.
    /// </summary>
    private void HoldUntilTheHostIsFree(Action post)
    {
        lock (_endingLock)
        {
            if (_active != null)
            {
                _heldForTheEnd.Add(post);
                return;
            }
        }

        post();
    }

    /// <summary>
    /// Owner decision 155A: frees the host from <paramref name="run"/>, which has ended, and hands back what
    /// its ending held, in the order it was made, for the caller to tell: one step under
    /// <see cref="_endingLock"/>, so nothing is held after it and an `init` reads the run in flight only
    /// before it. Owner decision 159A: and the Stops that reached the run, in <paramref name="stops"/>, for
    /// the caller to answer - a Stop decided after this step finds the host free.
    /// </summary>
    private List<Action> FreeTheHostFromTheRun(RemodelRun run, out List<string?> stops)
    {
        lock (_endingLock)
        {
            run.Phase = RemodelRunPhase.Finished;
            _active = null;
            _busy = false;
            var held = new List<Action>(_heldForTheEnd);
            _heldForTheEnd.Clear();
            stops = new List<string?>(_pendingStops);
            _pendingStops.Clear();
            return held;
        }
    }

    /// <summary>
    /// Owner decision 159A, on review (004 research R19.9; the race review's finding R3): lets go of a run Start set in
    /// flight and never handed to its scheduler, under the lock that frees the host, and takes back a stop asked for
    /// meanwhile. The stop when the copy goes away is decided under that lock on SOLIDWORKS' thread: it either reached the
    /// run before - told before the run's last word, and taken back here, so the plan, which stays startable, carries no
    /// stop into its next run - or finds no run in flight. Let go of outside the lock, after the run's last word, it was
    /// told after that word, and its flag stopped the next run before it began, answered `remodel.stopped` unasked. Called
    /// before that last word is told, and again as Start frees the host; the second finds nothing to do.
    /// </summary>
    private void LetGoOfARunNeverHandedOn(RemodelRun run)
    {
        lock (_endingLock)
        {
            _active = null;
            run.WithdrawStop();
        }
    }

    /// <summary>
    /// Owner decision 152A, on the Codex review (X2): holds the tool service's attachment for the plan
    /// or run that has just made the host busy (<see cref="RemodelHostOptions.HoldToolService"/>), and
    /// answers whether one could be held. Never waits: a hold is taken under the gate's lock alone. A
    /// delegate that throws is the press's failure, and the caller's <c>finally</c> frees the host.
    /// </summary>
    private bool HoldTheToolService()
    {
        IDisposable? hold = _options.HoldToolService();
        if (hold == null)
        {
            return false;
        }

        Interlocked.Exchange(ref _toolServiceHold, hold)?.Dispose();
        return true;
    }

    /// <summary>
    /// Lets go of the hold the plan or run took, once, on whichever thread frees the host - the
    /// message thread for a plan or a Start that handed nothing on, the run's own once its session is
    /// closed (<see cref="Execute"/>). Never throws: it comes before the host is freed (on review,
    /// N4), and a hold that fails as it is let go must neither keep the host busy - which would hold
    /// back every plan and every settings restart - nor reach a run's own thread, which no one waits
    /// on. The gate's own holds never fail.
    /// </summary>
    private void LetGoOfTheToolService()
    {
        try
        {
            Interlocked.Exchange(ref _toolServiceHold, null)?.Dispose();
        }
        catch (Exception)
        {
            // The hold's own failure, and the host is freed all the same.
        }
    }

    /// <summary>
    /// Whether a settings restart stands before the press. Only words for the page hang on it, so
    /// a reading that throws is none: the press goes on through the gate, which decides.
    /// </summary>
    private bool RestartAhead()
    {
        try
        {
            return _options.RestartAhead();
        }
        catch (Exception)
        {
            return false;
        }
    }

    // ---- the refusals two handlers share --------------------------------------------------

    /// <summary>
    /// One `error {error_class, message}` carrying the class whoever refused chose - the
    /// backend's reply body, or the pipeline's own pre-call refusal. One copy of it, because
    /// three handlers answer the same exception and three spellings of "pass the class through"
    /// is three chances to drop it. Owner decision 159A: what the page is told in place of the
    /// refusal's own sentence goes to the log, under <paramref name="what"/> was asked.
    /// </summary>
    private void SendRefusal(string? id, RemodelRefusal refusal, string what)
    {
        string words = PageWords(refusal);
        if (!string.Equals(words, refusal.Message, StringComparison.Ordinal))
        {
            Log(what, refusal);
        }

        _actions.SendError(id, refusal.ErrorClass, words, refusal.Retryable);
    }

    /// <summary>
    /// Owner decision 155A (004 research R18): the classes whose words on this tab are the host's own,
    /// whoever refused. The bridge refuses both with a sentence naming the part's full path, which the
    /// backend passes on unchanged (`BRIDGE_REFUSALS`) and the tool-service log keeps on the refused
    /// request's line; one sentence per class, the one the host already had for its own reading of the
    /// probe, is what the page prints.
    /// </summary>
    private static readonly Dictionary<string, string> TabWords =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "DocumentDirty", DocumentDirtyMessage },
            { "ExternalReferences", ExternalReferencesMessage },
        };

    /// <summary>
    /// Owner decision 159A (004 research R19): the tab's words for a refusal the review backend answered, by its class,
    /// where the backend's sentence can name a path - the part's, the run folder's, the bridge's pipe - and the class
    /// says what the engineer can do. Every other class the backend answers is told in
    /// <see cref="BackendFailedMessage"/>, but the ones it words plainly itself
    /// (<see cref="ClassesTheBackendWordsPlainly"/>).
    /// </summary>
    private static readonly Dictionary<string, string> BackendWords =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "NotAPart", NotAPartOnDiskMessage },
            { "BridgeUnavailable", BridgeNotAnsweringMessage },
            { "BackendUnavailable", BackendNotAnsweringMessage },
        };

    /// <summary>
    /// Owner decision 159A: the classes whose sentence the review backend writes in plain words that name no path, which
    /// the tab prints as they are: `ScopeRefused`, one sentence for each of the bridge's two codes (owner decision 149A,
    /// <c>SCOPE_REFUSAL_WORDS</c> in <c>chat/remodel.py</c>, pinned there word for word).
    /// </summary>
    private static readonly HashSet<string> ClassesTheBackendWordsPlainly =
        new HashSet<string>(StringComparer.Ordinal) { "ScopeRefused" };

    /// <summary>
    /// The words a failure reaches the page in, in a refusal and in the run line's `status {stage:
    /// "error"}` alike: <see cref="TabWords"/>' sentence for a refusal of one of its classes, whoever refused
    /// (owner decision 155A); and owner decision 159A (004 research R19), since every other sentence a failure
    /// carries can name a path: a refusal the review backend answered in <see cref="BackendWords"/>' words for
    /// its class, or <see cref="BackendFailedMessage"/> - but in its own for a class the backend words plainly;
    /// a refusal the add-in raised itself in its own words, which name no path; and any other failure in
    /// <see cref="UnexpectedFailureMessage"/>. What a failure said goes to the log where it is answered.
    /// </summary>
    private static string PageWords(Exception failure)
    {
        if (!(failure is RemodelRefusal refusal))
        {
            return UnexpectedFailureMessage;
        }

        if (TabWords.TryGetValue(refusal.ErrorClass, out string? words))
        {
            return words;
        }

        if (!TheBackendAnswered(refusal) || ClassesTheBackendWordsPlainly.Contains(refusal.ErrorClass))
        {
            return refusal.Message;
        }

        return BackendWords.TryGetValue(refusal.ErrorClass, out string? backends) ? backends : BackendFailedMessage;
    }

    /// <summary>
    /// Owner decision 159A: whether the review backend answered <paramref name="refusal"/> - the pipeline keeps the
    /// backend's answer as the cause of the refusal it raises for it (<c>BackendRemodelPipeline.Refusal</c>, pinned by
    /// <c>BackendRemodelPipelineTests</c>), and raises its own - no backend, no bridge, no copy to make active - with none.
    /// </summary>
    private static bool TheBackendAnswered(RemodelRefusal refusal) => refusal.InnerException is BackendRequestException;

    /// <summary>
    /// Owner decision 159A: the words a failure one of the shared rows caught reaches this tab in
    /// (<see cref="PaneActionsOptions.FailureWords"/>), its own message logged: View log's, which no View log can
    /// help; Show's; and Open report's and Open run folder's.
    /// </summary>
    private string SharedRowWords(string row, Exception failure)
    {
        Log(row, failure);
        switch (row)
        {
            case "log.open":
                return LogFolderNotOpenedMessage;

            case "entity.show":
                return ShowFailedMessage;

            case "report.open":
            case "folder.open":
                return NotOpenedMessage;

            default:
                return UnexpectedFailureMessage;
        }
    }

    /// <summary>
    /// Owner decision 159A (004 research R19): writes, for whoever debugs, what was said where the tab told it in its
    /// own words - <paramref name="said"/>, under <paramref name="what"/> was asked - on <see cref="RemodelHostOptions.Log"/>,
    /// masked as everything this host sends is (FR-015). Never throws: a log that cannot be written changes no answer.
    /// </summary>
    private void Log(string what, string said)
    {
        try
        {
            _options.Log(_actions.Redact("Remodel tab, " + what + ": " + said));
        }
        catch (Exception)
        {
            // The log is gone or full; the page's answer is what matters now.
        }
    }

    /// <summary>...a failure: a refusal's class and sentence, and the whole of anything else that threw.</summary>
    private void Log(string what, Exception failure) =>
        Log(what, failure is RemodelRefusal refusal ? refusal.ErrorClass + ": " + refusal.Message : failure.ToString());

    /// <summary>
    /// Owner decision 154A: a plan or a Start refuses a run root the run root rule refuses, in this tab's words,
    /// which its page shows whole - <paramref name="notDone"/> says what the press did not do, and the way on
    /// names the Settings on the Review tab, since this page has none (the reviews' finding F5) - before it does
    /// anything else.
    /// </summary>
    private bool RunRootRefused(string? id, string runRoot, string notDone) =>
        _actions.RefusedRunRoot(id, runRoot, notDone, RunRootRule.InSettingsOnTheReviewTab, PressAgain);

    /// <summary>What a plan or a Start refused for its run root says to do once the cause is gone (owner decision 154A).</summary>
    private const string PressAgain = "press Remodel a copy again";

    /// <summary>
    /// The run root a plan or a Start goes on under once its gate is passed (the reviews of decision 154A, N8):
    /// the run root in force, judged again when the gate's restart moved it from <paramref name="judged"/>; null
    /// once the press is answered with the refusal. Read once, with 153A's record of the settings in force: the gate
    /// holds back every settings restart, but not the add-in's first start of the backend, and while one that would
    /// bring another run root into force is under way there is none to go on under, and the press is refused.
    /// Written once for every start that passes a gate since owner decision 157A, the check tabs' too
    /// (<see cref="PaneActions.RunRootToUse"/>).
    /// </summary>
    private string? RunRootToUse(string? id, string judged, string notDone) =>
        _actions.RunRootToUse(
            id,
            judged,
            _options.RunRootForANewRun(),
            notDone,
            RunRootRule.InSettingsOnTheReviewTab,
            PressAgain);

    /// <summary>
    /// What a Start answers, <c>RunRootChanged</c>, when its plan's run folder is under a run root a settings save
    /// has since moved (the reviews of decision 154A, finding F6): the backend makes runs only under the one in
    /// force. No path; the way on is a new plan, under the run root in force.
    /// </summary>
    private const string StartRunRootChangedMessage =
        "this plan's run folder is under a run root that is no longer in force, and the backend makes runs only "
        + "under the one in force, so the plan was not applied. Press Remodel a copy again.";

    private void SendRunInProgress(string? id) =>
        _actions.SendError(
            id,
            "RunInProgress",
            "a remodel run is already in flight in this pane. One run at a time: two runs would "
            + "share one SOLIDWORKS session and neither could be attributed.",
            retryable: true);

    /// <summary>
    /// `RunNotFound` for a run folder the page named that this host has no record of, in
    /// <see cref="RunNotFoundMessage"/>'s plain words: the folder the page sent is not repeated (owner
    /// decision 155A).
    /// </summary>
    private void SendRunNotFound(string? id) =>
        _actions.SendError(id, "RunNotFound", RunNotFoundMessage, retryable: false);

    private void SendUnavailable(string? id, RemodelAvailability availability) =>
        _actions.SendError(
            id,
            "RemodelUnavailable",
            availability == RemodelAvailability.Unknown ? SeatCheckingMessage : NoSeatMessage,
            retryable: availability == RemodelAvailability.Unknown);

    private static Dictionary<string, object?>? DocumentPayload(PageDocument? document) =>
        document == null
            ? null
            : new Dictionary<string, object?>
            {
                { "path", document.Path },
                { "configuration", document.Configuration },
                { "kind", document.Kind },
            };

    /// <summary>
    /// The executor's one way to reach the page: the three unsolicited message types the
    /// contract defines and the stop flag, and nothing else.
    /// </summary>
    private sealed class RunReporter : IRemodelRunReporter
    {
        private readonly RemodelHost _host;
        private readonly RemodelRun? _run;

        public RunReporter(RemodelHost host, RemodelRun? run)
        {
            _host = host;
            _run = run;
        }

        /// <summary>
        /// False during the plan phase, which has no run to stop: `remodel.stop` is refused
        /// before a run exists, so there is no flag to read.
        /// </summary>
        public bool StopRequested => _run != null && _run.StopRequested;

        /// <summary>
        /// A stage the page ends its running state on waits for the run's ending while a run holds the host
        /// (owner decision 155A): the pipeline posts its own error before it answers, and the host is not
        /// free until `Execute` has closed the run's session.
        /// </summary>
        public void Status(string stage, string message)
        {
            if (EndsTheRunOnThePage(stage))
            {
                // Owner decision 159A (004 research R19): the pipeline's word that a run failed carries the
                // backend's or the transport's sentence, which can name a path; told in the tab's words, its own
                // logged, before the run's last word.
                string words = message;
                if (string.Equals(stage, "error", StringComparison.Ordinal))
                {
                    _host.Log("the run", message);
                    words = BackendFailedMessage;
                }

                _host.HoldUntilTheHostIsFree(() => _host.PostStatus(stage, words));
                return;
            }

            _run?.RememberStatus(stage, message);
            _host.PostStatus(stage, message);
        }

        public void Progress(int applied, int total, int seq, string kind, string? subjectName) =>
            _host._actions.Send("remodel.progress", null, new Dictionary<string, object?>
            {
                { "applied", applied },
                { "total", total },
                {
                    "current",
                    new Dictionary<string, object?>
                    {
                        { "seq", seq },
                        { "kind", kind },
                        { "subject_name", subjectName },
                    }
                },
            });

        public void Change(string changeRecordJson)
        {
            try
            {
                using (JsonDocument record = JsonDocument.Parse(changeRecordJson))
                {
                    _host._actions.Send("remodel.change", null, record.RootElement);
                }
            }
            catch (JsonException)
            {
                // Half a line is what a crash mid-write leaves behind. The file is the record;
                // the page's live list is a convenience and must not carry a fragment.
            }
        }
    }
}
