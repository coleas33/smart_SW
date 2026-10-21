using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.ToolService;

/// <summary>
/// One running tool service, behind a seam.
///
/// <see cref="ToolServiceHost"/> is the only implementation; the interface exists because
/// starting it needs a live <c>ISldWorks</c> and an attach on the SOLIDWORKS application
/// thread, and the decisions about *when* it starts and *who gets which secret* (T048) have to
/// be testable without either.
/// </summary>
public interface IToolService : IDisposable
{
    /// <summary>The <c>swreview-&lt;guid&gt;</c> name both clients connect to.</summary>
    string PipeName { get; }

    /// <summary>The document the scope is attached to.</summary>
    string DocumentPath { get; }

    /// <summary>
    /// Owner decision 152A: the configuration the scope is bound to - with
    /// <see cref="DocumentPath"/>, what this service's bridge answers to <c>ping</c>, read from the
    /// one attach that bound both.
    /// </summary>
    string? Configuration { get; }

    /// <summary>Pipe plus the review secret; goes to the backend's <c>POST /sessions</c>.</summary>
    BridgeConfig ReviewBridge { get; }

    /// <summary>Pipe plus the general-chat secret; goes to the generated CLI profile.</summary>
    BridgeConfig GeneralChatBridge { get; }

    /// <summary>
    /// Pipe plus the remodel secret; goes to the backend's remodel routes (T070, T134e) and to
    /// nothing else. It authorizes <c>remodel.*</c>, which is every write the run makes to the
    /// copy, so it is deliberately absent from <see cref="IToolServiceAccess"/>: the terminal
    /// can read its own generated profile.
    /// </summary>
    BridgeConfig RemodelBridge { get; }

    /// <summary>Whether this service attached a bridge-side SOLIDWORKS remodel seat.</summary>
    bool RemodelSeatAvailable { get; }

    /// <summary>
    /// 004 T158 (a design choice of 2026-09-26, research R13.8 D5): binds the run folder the host
    /// made with <c>RunFolders.CreateForRemodel</c> on this service's bridge, on the application
    /// thread with a bounded wait, for the next <c>remodel.open</c> to take and use up - never a
    /// folder taken from a request. The Remodel tab binds before every open; a bind that throws
    /// is refused as <c>BridgeUnavailable</c> and no open is sent.
    /// </summary>
    void BindRemodelRun(string runDirectory);

    /// <summary>The attached scope, so <c>entity.show</c> resolves against the same one.</summary>
    ISwSession Session { get; }

    /// <summary>
    /// One line into this service's own tool-service log, beside the <c>attached to ...</c>
    /// line the launch wrote.
    ///
    /// On the service rather than on the gate because the log belongs to the service: the gate
    /// outlives any one of them, and what it has to say - "I am not re-attaching to the document
    /// you just opened, because a turn is running", and since owner decision 158A "I no longer
    /// wait for a hold held past its limit" - is a fact about <i>this</i> attachment, and belongs
    /// in the file the engineer reads to find out what it is attached to. Must not throw; a log
    /// that cannot be written is not a reason to fail anything.
    /// </summary>
    void WriteLog(string line);
}

/// <summary>
/// What the Terminal tab needs from the tool service, and nothing else.
///
/// The terminal's profile writer (T057) has to put <c>{pipe, secret}</c> into the generated
/// CLI profile's MCP <c>env</c> block, and the run folder's persona text names the document.
/// It gets those two facts through this interface rather than a reference to the gate, so the
/// terminal can never reach the <b>review</b> secret: that one authorizes <c>interference</c>
/// as well, and the CLI can read its own generated profile (contracts/README.md).
///
/// Both members answer null until the tool service is listening, which is a state the pane
/// really has - the Task Pane exists before the first document is open.
/// </summary>
public interface IToolServiceAccess
{
    /// <summary>Where to connect and the general-chat secret, or null before the start.</summary>
    BridgeConfig? GeneralChatBridge { get; }

    /// <summary>The document the scope is attached to, or null before the start.</summary>
    string? DocumentPath { get; }
}

/// <summary>
/// Owner decision 158A: the kind of work that holds the tool service's attachment
/// (<see cref="ToolServiceGate.HoldAttachment"/>). The gate names it, in fixed words, in the
/// tool-service log when it ignores a hold held past <see cref="ToolServiceGate.HoldLimit"/>, so that
/// line says what held and never a path. The add-in names one for each host it hands the hold to.
/// </summary>
public enum ToolServiceHolder
{
    /// <summary>A review session's start, from before it reads the bridge until its session is tracked.</summary>
    ReviewSession,

    /// <summary>A page call that starts a turn, while the pane's proxy has it out.</summary>
    TurnCall,

    /// <summary>A Remodel plan or run, until the Remodel host is free again: the host's one hold, for either.</summary>
    Remodel,
}

/// <summary>
/// T048. Owns the tool service's lifetime inside the add-in: start it once a document is open,
/// hand the review half to the backend and keep the general-chat half for the terminal, stop it
/// on disconnect.
///
/// Three things it exists to get right, none of which belong in a COM event handler:
///
/// <b>Not before the first document.</b> SOLIDWORKS normally loads with nothing open, and the
/// Task Pane is created either way. <see cref="ToolServiceHost.Start"/> walks the component
/// tree; with no document there is nothing to walk. So the pane asks on connect and again on
/// every <c>ActiveDocChangeNotify</c>, and this answers "not yet" until there is something to
/// attach to.
///
/// <b>And not to a drawing.</b> "Something to attach to" is a part or an assembly
/// (<see cref="PageDocument.IsAttachable"/>). A drawing has no configuration, and a session is
/// bound to one, so the attach throws - and a throw here is swallowed into addin.log, which is
/// how a SOLIDWORKS loaded with a drawing active used to leave every bridge-backed feature off
/// for the session. Both entry points refuse one, and both say so through
/// <c>report</c>: a refusal nobody can see is the same as the failure it replaced.
///
/// <b>Off the application thread.</b> <see cref="ToolServiceHost.Start"/> marshals its attach
/// onto the application thread and waits for it. Both callers - <c>ConnectToSW</c> and the
/// document-changed event - <i>are</i> that thread, so starting inline would deadlock
/// SOLIDWORKS until the attach timeout expired. The start is therefore scheduled; the delegate
/// is injectable so the tests are deterministic.
///
/// <b>Once.</b> `ToolService 1 per add-in instance` (data-model.md): a second host would be a
/// second pipe, a second scope and a second pair of secrets, and a review already running would
/// still be talking to the first. A start that *failed* is not a start, so the next document
/// tries again - an attach can fail on the document that happened to be open and succeed on the
/// next one, and the alternative is a pane whose tools are dead until SOLIDWORKS restarts.
///
/// <b>And it follows the active document.</b> "Once" above is about one service at a time, not
/// about one document per SOLIDWORKS session: the scope is bound to the document it attached
/// to, so an engineer who opens another one gets `document no longer open` from every command
/// until the add-in is reloaded (docs/history/pane-findings-2026-09-16.md, finding 1).
/// <see cref="FollowDocument"/> is the second entry point that fixes that, and it is separate
/// from <see cref="EnsureStarted"/> because the two answer different questions: "is there one?"
/// and "is it the right one?".
///
/// <b>And it follows once the hold ends</b> (owner decision 152A). A switch made while a review
/// turn or a remodel run holds the bridge is skipped, as before; the gate now owes the follow and
/// asks again every <see cref="FollowPoll"/> until nothing holds the bridge, then attaches to the
/// document active at that moment. It asks rather than being told: a turn begins and ends on the
/// backend - a follow-up, an answer or a Send reaches it without the host - and the add-in learns
/// that one has ended only by asking, as the settings restart's watcher asks (owner decision 143A).
/// A switch that lands while a start or a follow is in flight is owed too, and looked at as soon as
/// that work is over, so no switch is lost to one in progress. Such a follow is a switch's, and is
/// made as at the switch: by the path, so a configuration switch re-attaches nothing wherever it
/// lands (004, decision 22A). And a review that finds the bridge on another document than its own
/// asks the gate to follow the active document as it is, its configuration included
/// (<see cref="FollowActiveDocument"/>), which is how a configuration switch reaches the bridge
/// before that review runs.
///
/// <b>And work holds the bridge through it</b> (owner decision 152A, on the Codex review: X2). The
/// busy question is a round trip, and work can begin while it is out: so a remodel plan or run, a
/// review session being made and a turn being started through the pane each hold the attachment
/// (<see cref="HoldAttachment"/>) before they read the bridge, and a follow takes the bridge down
/// only if, under the lock the holds are taken under, none is held and none was taken since it
/// noted them before its question.
///
/// <b>And a hold by itself holds the bridge for an hour at most</b> (owner decision 158A). Each holder
/// lets go when its work ends, but one that never let go would keep the tool service on its document
/// for good. A hold held longer than <see cref="HoldLimit"/> no longer holds back a follow by itself,
/// and is said once in the tool-service log by its holder's kind and how long it held. Its work is not
/// stopped, and the busy question is asked as for no hold, so a follow still waits for a turn the
/// backend has marked running, or a remodel plan or run in progress - which the limit does not bound.
///
/// Thread-safe, because it is not called from one thread: the pane's calls come from the
/// application thread and the start itself completes on a worker.
/// </summary>
public sealed class ToolServiceGate : IToolServiceAccess, IDisposable
{
    /// <summary>
    /// How long a follow owed while work holds the bridge waits before the gate asks again (owner
    /// decision 152A): a second, as the settings restart's watcher waits (143A). A look costs the
    /// add-in the busy question - the remodel run, then one `GET /sessions/{chat_id}` per review it
    /// tracks until one does not rule a turn out - off the application thread, and only while a
    /// follow is owed.
    /// </summary>
    public static readonly TimeSpan FollowPoll = TimeSpan.FromSeconds(1);

    /// <summary>
    /// How long a hold by itself holds back a follow (owner decision 158A): an hour. A hold held longer
    /// no longer does - the look that finds it so asks the busy question as for no hold - and is said
    /// once in the tool-service log, by its holder's kind and how long it held. Nothing else is done to
    /// it: its work is not stopped, and letting it go later lets go of nothing more.
    ///
    /// <b>Why an hour.</b> The limit is for the holds the busy question cannot see while they hold: a
    /// review session's start, which holds until `POST /sessions` gives up, after the backend client's
    /// 30 seconds, and a page call that starts a turn, which holds until the proxy's 120 seconds, before
    /// the backend has marked its turn running. An hour is thirty times the longer of the two, so neither
    /// meets it working, and one that never let go holds the follow back an hour and a poll, not for
    /// ever. A remodel plan or run is bounded by no time: its hold covers the model's judgement turn,
    /// which only its steps bound, its twenty minutes of changes (004, <see cref="RemodelLimits"/>), the
    /// after-dump, the verification, the save and the close, so a healthy one can outlast the hour, and
    /// its hold is then said. But the Remodel host is busy whenever it holds, and the add-in's busy
    /// question reads a plan or a run in progress first, so the bridge is never taken down under one,
    /// past the limit or not, and one that never ended would hold the follow back through the busy
    /// question, which this limit does not bound. A plan or a run is not exempt: an exemption would
    /// change only the line (on the decision's review: S1, S3).
    /// </summary>
    public static readonly TimeSpan HoldLimit = TimeSpan.FromHours(1);

    /// <summary>
    /// What a follow owes (owner decision 152A, ordered so that the larger debt covers the smaller):
    /// nothing; a switch's follow, made as at the switch, by the document's path; or a review's
    /// request, made by the review's own rule, the path ignoring case and the configuration exactly.
    /// </summary>
    private enum Owed
    {
        Nothing,
        Path,
        Configuration,
    }

    private readonly Func<PageDocument?> _activeDocument;
    private readonly Func<IToolService> _start;
    private readonly Action<IToolService?> _publish;
    private readonly Action<string, Exception?> _report;
    private readonly Action<Action> _schedule;
    private readonly Func<bool> _busy;
    private readonly Func<string, string, bool>? _preserveAttachment;
    private readonly Action<IToolService> _afterStopped;
    private readonly Action<Action> _later;
    private readonly Func<TimeSpan> _clock;
    private readonly TimeSpan _holdLimit;
    private readonly object _lock = new object();

    private IToolService? _service;
    private bool _starting;
    private bool _disposed;

    /// <summary>
    /// Owner decision 152A: what is owed - a follow skipped while work held the bridge, a switch that
    /// landed while a start or a follow was in flight, or a review's request - and not made since.
    /// Taken by a follow as it asks whether work holds the bridge, and by a follow or a start as it
    /// reads the active document to act on it: whatever is asked after that is owed afresh. Guarded
    /// by <see cref="_lock"/>.
    /// </summary>
    private Owed _owed;

    /// <summary>
    /// Owner decision 152A: a look again is scheduled and has not run yet, so no second one is.
    /// Guarded by <see cref="_lock"/>.
    /// </summary>
    private bool _asking;

    /// <summary>
    /// Owner decision 152A, on the Codex review (X2): holds taken on the service listening now and not
    /// let go - work running over its bridge (<see cref="HoldAttachment"/>) - each with its holder's
    /// kind and when it was taken. Owner decision 158A: less any a follow found held longer than
    /// <see cref="HoldLimit"/>, taken out then, so each is said once and holds nothing after. Guarded by
    /// <see cref="_lock"/>.
    /// </summary>
    private readonly List<Hold> _held = new List<Hold>();

    /// <summary>
    /// ...and every hold ever taken, counted: a follow notes it before it asks whether work holds the
    /// bridge, and takes the bridge down only if none was taken since. Guarded by <see cref="_lock"/>.
    /// </summary>
    private long _holdsTaken;

    /// <param name="activeDocument">SOLIDWORKS' active document, or null when nothing is open.
    /// The document rather than a yes/no, because a drawing is open and is still not something a
    /// scope can be attached to. Asked on the scheduled thread, so it may marshal onto the
    /// application thread itself.</param>
    /// <param name="start">Starts the host. Blocks; see the class remarks.</param>
    /// <param name="publish">Publishes the review half of whichever service is listening - in
    /// the add-in, into <see cref="ReviewHostOptions.Bridge"/>, which is what
    /// <c>POST /sessions</c> carries - and is called with null when one stops, so that what is
    /// published is never a pipe that has been closed. Every change of <see cref="Attachment"/>
    /// is published, and <see cref="Attachment"/> already answers the new state when it is: the
    /// Remodel tab refreshes capability from this callback; lost-plan notification follows the
    /// disposal attempt through <paramref name="afterStopped"/> (T180).</param>
    /// <param name="report">A failed start, or a document not attached to, for the pane and the
    /// add-in log. The exception is null when nothing threw: a refusal is not a failure, but it
    /// is just as invisible if it is not said.</param>
    /// <param name="schedule">Where the start runs. Defaults to the thread pool.</param>
    /// <param name="busy">Whether work is holding the bridge - in the add-in, a review turn or
    /// a remodel run. Asked by every follow, on the scheduled thread and off the lock, because
    /// the add-in's answer costs an HTTP round trip per open chat. Defaults to "never busy",
    /// which is right for a gate with no work to hold it. Work that holds the attachment
    /// (<see cref="HoldAttachment"/>) holds the bridge whatever this answers, and a follow that
    /// finds a hold held asks it nothing.</param>
    /// <param name="preserveAttachment">Whether the exact active copy still belongs to a held
    /// planned session on this pipe. Optional; called off the lock on the scheduled thread.</param>
    /// <param name="afterStopped">Notification after the Dispose attempt, including a thrown or
    /// deferred cleanup. Returning from Dispose alone proves no cleanup facts.</param>
    /// <param name="later">Where a look again runs once a follow is owed while work holds the
    /// bridge (owner decision 152A): once, after <see cref="FollowPoll"/>, off the caller's thread.
    /// Defaults to a delay on the thread pool; injectable so the tests are deterministic.</param>
    /// <param name="clock">What the time is, off which when each hold was taken and how long it has
    /// held are read (owner decision 158A). Defaults to a stopwatch of the gate's own: a clock that only
    /// goes forward, so a change of the system's time neither ages a hold nor keeps one young. Read
    /// under the gate's lock, so it must not wait; injectable so the tests are deterministic.</param>
    /// <param name="holdLimit">How long a hold holds back a follow: <see cref="HoldLimit"/>, which the
    /// add-in keeps. Injectable so a case can see the gate's own clock age a hold in a quarter of a
    /// second; one of no time or less is refused.</param>
    public ToolServiceGate(
        Func<PageDocument?> activeDocument,
        Func<IToolService> start,
        Action<IToolService?> publish,
        Action<string, Exception?> report,
        Action<Action>? schedule = null,
        Func<bool>? busy = null,
        Func<string, string, bool>? preserveAttachment = null,
        Action<IToolService>? afterStopped = null,
        Action<Action>? later = null,
        Func<TimeSpan>? clock = null,
        TimeSpan? holdLimit = null)
    {
        _activeDocument = activeDocument ?? throw new ArgumentNullException(nameof(activeDocument));
        _start = start ?? throw new ArgumentNullException(nameof(start));
        _publish = publish ?? throw new ArgumentNullException(nameof(publish));
        _report = report ?? throw new ArgumentNullException(nameof(report));
        _schedule = schedule ?? (work => ThreadPool.QueueUserWorkItem(_ => work()));
        _busy = busy ?? (() => false);
        _preserveAttachment = preserveAttachment;
        _afterStopped = afterStopped ?? (_ => { });
        _later = later ?? (work => Task.Delay(FollowPoll).ContinueWith(_ => work(), TaskScheduler.Default));
        Stopwatch ownClock = Stopwatch.StartNew();
        _clock = clock ?? (() => ownClock.Elapsed);

        // Refused here, as a poll the restart's watcher could not wait out is (DeferredRestart), rather
        // than ignoring every hold the moment it is taken (owner decision 158A, on its review: R2).
        if (holdLimit <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(
                nameof(holdLimit), holdLimit, "a hold limit must be longer than no time at all.");
        }

        _holdLimit = holdLimit ?? HoldLimit;
    }

    /// <summary>
    /// Owner decision 152A: the document and configuration the service listening on
    /// <paramref name="bridge"/>'s pipe is attached to - what that bridge answers to <c>ping</c>,
    /// read from the service's record of its attach rather than over its pipe, where it would wait
    /// behind every command ahead of it on the application thread - or null when no service
    /// listening now has that pipe: before the first start, another attachment's, one a re-attach
    /// is taking down, and any after <see cref="Dispose"/>. A pipe name is minted per start, so it
    /// names one attachment, and a pipe that is closed serves no document. What a review asks
    /// before its session is given the bridge.
    /// </summary>
    public PageDocument? DocumentServedBy(BridgeConfig bridge)
    {
        if (bridge == null)
        {
            throw new ArgumentNullException(nameof(bridge));
        }

        IToolService? service = Service;
        return service != null && string.Equals(service.PipeName, bridge.Pipe, StringComparison.Ordinal)
            ? new PageDocument(service.DocumentPath, service.Configuration)
            : null;
    }

    /// <summary>
    /// Owner decision 152A: asked by a review that found the bridge on another document than its
    /// own. The gate follows the document active now as the review compares it - the path ignoring
    /// case and the configuration exactly, <see cref="PageDocument.IsSameDocument(PageDocument)"/>,
    /// so that what it calls the same the review does too (the 152A review's R3) - as any follow is
    /// made: not while work holds the bridge, when it waits for the hold to end; not away from the
    /// planned copy a waiting plan holds (004 T180); and to nothing for a drawing or no document.
    /// Returns at once: everything but the decision to schedule runs on the scheduled thread. Never
    /// throws.
    /// </summary>
    public void FollowActiveDocument()
    {
        bool look;
        lock (_lock)
        {
            if (_disposed)
            {
                return;
            }

            // Owed whatever happens next: a follow or a start in flight looks again when it ends
            // (Settle), and with none listening there is nothing to follow from.
            Owe(Owed.Configuration);
            look = !_starting && !_asking && _service != null;
            if (look)
            {
                _asking = true;
            }
        }

        if (look)
        {
            Ask(_schedule, LookAgain);
        }
    }

    /// <summary>
    /// Owner decision 152A, on the Codex review (X2): holds the service listening now for work about to
    /// run over its bridge - a remodel plan or run, a review session being made, a turn being started -
    /// so that no follow takes it down until the hold is let go; or null when no service is listening to
    /// hold: none has started, a follow has begun taking one down and the next is not listening yet, or
    /// the gate is disposed. Work that finds none starts on no bridge being taken down - it is refused,
    /// or goes on with the bridge it was given, as each host says - and waits for nothing.
    ///
    /// <b>Why a hold, and not the busy question alone.</b> A follow asks whether work holds the bridge
    /// before it takes it down, and the add-in's answer is a round trip per open chat: work can begin
    /// while the question is out, after its answer was had, and a remodel plan making its copy active
    /// is not yet the plan a held copy keeps the attachment for (004 T180). So the hold is taken under
    /// the gate's lock, and the follow takes the bridge down under that lock only if no hold is held and
    /// none was taken since it noted them, before its question: the two cannot pass each other. A hold
    /// held when a follow begins answers its busy question without the round trip.
    ///
    /// Taken and let go under the gate's lock, which is never held while anything is waited for, so
    /// this never waits either - on the SOLIDWORKS application thread least of all. Disposing the hold
    /// lets it go; disposing it again does nothing.
    ///
    /// <b>For an hour at most</b> (owner decision 158A): a hold held longer than <see cref="HoldLimit"/>,
    /// measured from when it was taken, no longer holds back a follow by itself, and is said once in the
    /// tool-service log by <paramref name="holder"/>'s kind and how long it held - never a path. Its work
    /// is not stopped, and letting it go afterwards lets go of nothing more.
    /// </summary>
    /// <param name="holder">The kind of work that holds: what that line names.</param>
    public IDisposable? HoldAttachment(ToolServiceHolder holder)
    {
        lock (_lock)
        {
            if (_disposed || _service == null)
            {
                return null;
            }

            var hold = new Hold(this, holder, _clock());
            _held.Add(hold);
            _holdsTaken++;
            return hold;
        }
    }

    /// <summary>
    /// A hold on the gate, let go once (<see cref="HoldAttachment"/>): what holds, and when on the gate's
    /// clock it was taken (owner decision 158A).
    /// </summary>
    private sealed class Hold : IDisposable
    {
        private ToolServiceGate? _gate;

        public Hold(ToolServiceGate gate, ToolServiceHolder holder, TimeSpan takenAt)
        {
            _gate = gate;
            Holder = holder;
            TakenAt = takenAt;
        }

        public ToolServiceHolder Holder { get; }

        public TimeSpan TakenAt { get; }

        public void Dispose() => Interlocked.Exchange(ref _gate, null)?.LetGo(this);
    }

    /// <summary>
    /// A hold let go. A follow it kept owed is looked at when its poll comes due, as any follow owed
    /// while work holds the bridge is. Owner decision 158A: one a follow ignored past the limit was
    /// taken out of the holds then, so letting it go now lets go of nothing - of no other hold, as a
    /// count of holds would have - and says nothing, its line written when it was ignored.
    /// </summary>
    private void LetGo(Hold hold)
    {
        lock (_lock)
        {
            _held.Remove(hold);
        }
    }

    /// <summary>
    /// Owner decision 158A: takes out of the holds every one held longer than the limit, each measured
    /// from when it was taken - so a hold taken as another passes the limit still holds - and answers
    /// what each was and how long it had held, for the caller to say once the lock is let go. Under
    /// <see cref="_lock"/>.
    /// </summary>
    private List<(ToolServiceHolder Holder, TimeSpan Held)> TakeHoldsPastTheLimit()
    {
        var ignored = new List<(ToolServiceHolder Holder, TimeSpan Held)>();
        if (_held.Count == 0)
        {
            return ignored;
        }

        TimeSpan now = _clock();
        for (int index = 0; index < _held.Count;)
        {
            Hold hold = _held[index];
            TimeSpan held = now - hold.TakenAt;
            if (held > _holdLimit)
            {
                _held.RemoveAt(index);
                ignored.Add((hold.Holder, held));
            }
            else
            {
                index++;
            }
        }

        return ignored;
    }

    /// <summary>
    /// Owner decision 158A: the tool-service log's line for a hold ignored past the limit - what held, in
    /// fixed words, and for how long, and never a path or a document's name. "By itself": the busy
    /// question still keeps the bridge under a turn the backend has marked running, or a remodel plan or
    /// run in progress, so the line is true of every holder (on its review).
    /// </summary>
    private string IgnoredLine(ToolServiceHolder holder, TimeSpan held) =>
        "ignoring a hold by " + HolderWords(holder) + ": held for " + HoursMinutesSeconds(held)
        + ", longer than the " + HoursMinutesSeconds(_holdLimit) + " limit, so it no longer holds back "
        + "following the active document by itself; its work is not stopped";

    private static string HolderWords(ToolServiceHolder holder) => holder switch
    {
        ToolServiceHolder.ReviewSession => "a review session's start",
        ToolServiceHolder.TurnCall => "a page call that starts a turn",
        ToolServiceHolder.Remodel => "a Remodel plan or run",
        _ => "work of kind " + ((int)holder).ToString(CultureInfo.InvariantCulture),
    };

    /// <summary><c>h:mm:ss</c>, the hours counted on past a day.</summary>
    private static string HoursMinutesSeconds(TimeSpan span) =>
        ((long)span.TotalHours).ToString(CultureInfo.InvariantCulture)
        + span.ToString(@"\:mm\:ss", CultureInfo.InvariantCulture);

    /// <summary>The running service, or null. Null is an ordinary state, not a failure.</summary>
    public IToolService? Service
    {
        get
        {
            lock (_lock)
            {
                return _service;
            }
        }
    }

    public BridgeConfig? GeneralChatBridge => Service?.GeneralChatBridge;

    /// <summary>
    /// The remodel half, for the Remodel tab's pipeline (T134e). Read fresh per call like the
    /// others - the tool service restarts with the document - and null before it is listening,
    /// which is what makes the pane refuse a run rather than start one it cannot execute.
    ///
    /// On the gate and on <see cref="IToolService"/>, never on <see cref="IToolServiceAccess"/>:
    /// that interface is the terminal's view, and this secret authorizes every write the
    /// re-modeler makes to the copy.
    /// </summary>
    public BridgeConfig? RemodelBridge => Service?.RemodelBridge;

    /// <summary>
    /// The Remodel tab's capability, read from the current service. Before attach completes
    /// there is no answer yet; once it does, a missing seat is an explicit unavailable state.
    /// </summary>
    public RemodelAvailability RemodelCapability
    {
        get
        {
            IToolService? service = Service;
            return service == null
                ? RemodelAvailability.Unknown
                : service.RemodelSeatAvailable
                    ? RemodelAvailability.Available
                    : RemodelAvailability.Unavailable;
        }
    }

    public string? DocumentPath => Service?.DocumentPath;

    /// <summary>
    /// Which attachment is listening, as the pipe name it was started with; null before the
    /// first start, while a re-attach is in flight, after a start that failed and after
    /// <see cref="Dispose"/> (decision 22A, 004 T160).
    ///
    /// <see cref="PipeNames"/> mints the name fresh for every start, so it names one
    /// attachment - one bridge dispatcher, and the one remodel session that dispatcher can
    /// hold - even when two attachments in a row are to the same document. That is why the
    /// Remodel tab records this on each plan and compares it at Start rather than
    /// <see cref="DocumentPath"/>: a re-attach back to the same document has still thrown the
    /// plan's session away. It is the pipe's name, not its secret; the name alone reaches
    /// nothing.
    /// </summary>
    public string? Attachment => Service?.PipeName;

    /// <summary>
    /// The attached scope, for <c>entity.show</c>. Null before the tool service is listening,
    /// where the resolver falls back to its own attach.
    /// </summary>
    public ISwSession? Session => Service?.Session;

    /// <summary>
    /// 004 T158: binds <paramref name="runDirectory"/> on the service listening now
    /// (<see cref="IToolService.BindRemodelRun"/>), read fresh like everything else here, because
    /// the service restarts with the document. With none listening - before the first start,
    /// mid-restart, after a failed start or <see cref="Dispose"/> - it throws, so the Remodel tab
    /// refuses the open rather than sending one no bridge can take (lane D's default,
    /// 2026-09-27). Whatever the service throws passes through unchanged.
    /// </summary>
    public void BindRemodelRun(string runDirectory)
    {
        IToolService service = Service ?? throw new InvalidOperationException(
            "no SwReview tool service is listening, so there is no bridge to bind the run folder on.");
        service.BindRemodelRun(runDirectory);
    }

    /// <summary>
    /// Starts the tool service if a document is open and one is not running already. Returns
    /// immediately: the work is scheduled. Never throws - the add-in calls this from a
    /// SOLIDWORKS callback, where an exception is the session's problem rather than ours.
    /// </summary>
    public void EnsureStarted()
    {
        lock (_lock)
        {
            if (_disposed || _service != null || _starting)
            {
                return;
            }

            _starting = true;
        }

        try
        {
            _schedule(StartCore);
        }
        catch (Exception failure)
        {
            ClearStarting();
            _report("The SwReview tool service could not be scheduled.", failure);
        }
    }

    /// <summary>
    /// Re-attaches the tool service to <paramref name="activePath"/> when it is attached to
    /// something else. Returns immediately: everything but the decision to schedule runs on the
    /// scheduled thread, exactly as the first start did, so the callback that publishes the
    /// review bridge re-points it too. Never throws - the add-in calls this from
    /// <c>ActiveDocChangeNotify</c>.
    ///
    /// <b>Nothing expensive on the caller's thread.</b> The caller is the SOLIDWORKS
    /// application thread (the class remarks above), and the two expensive things here are
    /// paid per document switch: the add-in's busy question is an HTTP round trip per open
    /// chat, each with the backend client's 30-second timeout, and the teardown joins the
    /// pipe's accept thread, every client thread and its pump. Asking either inline would
    /// freeze SOLIDWORKS for the better part of a minute when the backend is wedged - which is
    /// exactly when the engineer is most likely to be switching documents. So the checks below
    /// are the cheap ones (a string compare and a canonicalization), and everything after them
    /// is <see cref="FollowCore"/>, on the scheduled thread.
    ///
    /// Four cases it deliberately does nothing in:
    ///
    /// <b>Nothing open.</b> A null or blank active path means SOLIDWORKS has no document, not
    /// that the attachment is wrong. Dropping the service there would cost a restart for every
    /// close, and a command against the closed document still answers with its name.
    ///
    /// <b>A drawing.</b> The same answer for the same reason, and it matters more here than in
    /// <see cref="EnsureStarted"/>: the re-attach takes the running service down <i>first</i>,
    /// so before this case existed, opening a drawing to look at it disposed a bridge that was
    /// working and the attach that would have replaced it threw.
    ///
    /// <b>The same document.</b> Compared canonically and case-insensitively: SOLIDWORKS is
    /// under no obligation to spell a path the way it spelt it at attach time, and a restart
    /// per document change would be a new pipe, a new scope and a new pair of secrets for
    /// nothing.
    ///
    /// <b>Work is holding the bridge.</b> A review turn or a remodel run is executing commands
    /// against this scope; disposing it underneath them fails work that was going fine. The
    /// engineer is told through the tool-service log rather than by a silent no-op, because
    /// this is the one case where the bridge really does keep answering about the other
    /// document. A busy question that throws counts as busy: a teardown cannot be undone. A
    /// remodel plan waiting for Start does not make the host busy (decision 22A). T180 preserves
    /// its original attachment only while its exact held copy is active; an ordinary document
    /// switch still tears it down. The Remodel tab refuses a lost plan by name, and tells the
    /// engineer after the disposal attempt without claiming delayed cleanup succeeded. Since owner
    /// decision 152A the skipped switch is owed, and followed once the hold ends (the class
    /// remarks).
    ///
    /// A configuration switch reaches this method as the same path, and is the same document case:
    /// it re-attaches nothing at the switch (004, decision 22A). A follow made for any other reason
    /// - a hold that ended, a review's request - attaches to the document as it is, its
    /// configuration included.
    /// </summary>
    public void FollowDocument(string? activePath)
    {
        if (string.IsNullOrWhiteSpace(activePath))
        {
            return;
        }

        IToolService? attached = null;
        bool skipped = false;
        lock (_lock)
        {
            if (_disposed || (_service == null && !_starting))
            {
                // No service at all is EnsureStarted's business, not this method's.
                return;
            }

            if (_starting)
            {
                // A start or a follow is in flight. It reads the active document when it runs, but
                // this switch can land after that reading, and was then dropped until the next
                // switch: it is owed instead, as a switch's follow, and looked at once that work is
                // over (owner decision 152A; Settle).
                Owe(Owed.Path);
                return;
            }

            if (SameDocument(_service!.DocumentPath, activePath!))
            {
                return;
            }

            if (!Attachable(activePath!))
            {
                // A drawing, so this is the "nothing open" case above rather than a document
                // worth re-attaching to: the running service keeps its scope, its pipe and its
                // secrets, and the engineer who opens a drawing to read it still has a bridge
                // when they come back. Reported below rather than here, because the report
                // reaches the pane and nothing that touches the pane may hold this lock.
                skipped = true;
            }
            else
            {
                attached = _service;

                // Claimed here, on the caller's thread, rather than in FollowCore: it is what
                // keeps an EnsureStarted or a second document change arriving in the gap from
                // scheduling a start of its own. The service stays published until FollowCore
                // takes it down, so the pane keeps answering about the document it is really
                // attached to.
                _starting = true;
            }
        }

        if (skipped)
        {
            _report(SkippedMessage(activePath!), null);
            return;
        }

        try
        {
            _schedule(() => FollowCore(attached!, activePath!));
        }
        catch (Exception failure)
        {
            ClearStarting();
            _report("The SwReview tool service could not be scheduled.", failure);
        }
    }

    /// <summary>
    /// The rest of a follow, on the scheduled thread, with <c>_starting</c> already claimed: ask
    /// whether work is holding the bridge, and if not, follow the document active now
    /// (<see cref="FollowNow"/>). While work holds it, the follow is owed and asked again a poll
    /// later (owner decision 152A); the tool-service log says why once, for the switch that was
    /// skipped - <paramref name="switchedTo"/>, null for a look again, which writes nothing.
    /// </summary>
    private void FollowCore(IToolService attached, string? switchedTo)
    {
        // What this follow is for: what was owed when it asks - taken now, so that whatever is asked
        // while the question is out is owed afresh (the 152A review's N2) - and a switch's own follow
        // at least. And the holds taken so far, noted before the question is asked (the Codex review's
        // X2): one taken while it is out keeps the bridge (FollowNow), and one held now is work holding
        // the bridge, answered without the question's round trip. Owner decision 158A: less any hold held
        // longer than the limit, taken out now and said below, once the lock is let go.
        Owed owed;
        long holdsTaken;
        bool held;
        List<(ToolServiceHolder Holder, TimeSpan Held)> ignored;
        lock (_lock)
        {
            owed = Take();
            holdsTaken = _holdsTaken;
            ignored = TakeHoldsPastTheLimit();
            held = _held.Count > 0;
        }

        foreach ((ToolServiceHolder holder, TimeSpan heldFor) in ignored)
        {
            Log(attached, IgnoredLine(holder, heldFor));
        }

        if (switchedTo != null && owed < Owed.Path)
        {
            owed = Owed.Path;
        }

        bool busy = held;
        if (!held)
        {
            try
            {
                busy = _busy();
            }
            catch (Exception failure)
            {
                // A question that cannot be answered counts as busy - nothing is torn down - and is
                // said, as before 152A; this follow is not asked again every poll, since nothing says
                // the next answer would come: the next switch, or a review's request, asks again. A
                // switch that landed while the question was out is owed, and looked at now (Settle).
                Settle();
                _report("The SwReview tool service could not be asked whether it is busy.", failure);
                return;
            }
        }

        if (busy)
        {
            LogSkipped(attached, switchedTo);
            Defer(owed);
            return;
        }

        FollowNow(attached, owed, holdsTaken, switchedTo);
    }

    /// <summary>
    /// The tool-service log's one line for a switch skipped while work holds the bridge - the one case
    /// where the bridge really does keep answering about the other document - and nothing for a look,
    /// <paramref name="switchedTo"/> null, which would write it every poll.
    /// </summary>
    private static void LogSkipped(IToolService attached, string? switchedTo)
    {
        if (switchedTo != null)
        {
            Log(attached, "not re-attaching to " + switchedTo + ": a turn is running against " + attached.DocumentPath);
        }
    }

    /// <summary>
    /// A follow once nothing holds the bridge: the document active now, read now - never an older
    /// event's - is followed, unless it is no part or assembly at all, the exact held copy of a
    /// waiting plan (004 T180), or the one attached to - by its path for a switch's follow, as at the
    /// switch, and by the review's own rule for a review's request, its configuration included (owner
    /// decision 152A; <see cref="Serves"/>) - and not while work holds the bridge that began holding it
    /// while the busy question was out (the Codex review's X2; <paramref name="holdsTaken"/>, the holds
    /// taken before the question was asked).
    /// </summary>
    private void FollowNow(IToolService attached, Owed owed, long holdsTaken, string? switchedTo)
    {
        PageDocument? current;
        bool preserve = false;
        try
        {
            lock (_lock)
            {
                // Acted on now: what was asked while the busy question was out is this follow's too,
                // and whatever is asked after this reading is owed afresh.
                Owed meanwhile = Take();
                if (meanwhile > owed)
                {
                    owed = meanwhile;
                }
            }

            current = _activeDocument();
            if (current == null || !current.IsAttachable || Serves(attached, current, owed))
            {
                Settle();
                return;
            }

            if (_preserveAttachment != null)
            {
                preserve = _preserveAttachment(current.Path, attached.PipeName);
            }
        }
        catch (Exception failure)
        {
            Settle();
            _report("The SwReview tool service could not be asked whether it is busy.", failure);
            return;
        }

        if (preserve)
        {
            Settle();
            Log(attached, "not re-attaching to " + current.Path + ": the planned copy still belongs to " + attached.DocumentPath);
            return;
        }

        bool heldMeanwhile;
        lock (_lock)
        {
            if (_disposed || !ReferenceEquals(_service, attached))
            {
                // Disposed, or Dispose took the service down, while this was queued or while
                // the busy question was out. Either way there is nothing left to re-attach.
                _starting = false;
                return;
            }

            // Owner decision 152A, on the Codex review (X2): work that took a hold since the holds were
            // noted, before the busy question - after its answer was had - holds the bridge, held now
            // or let go since, and its turn or its run may be under way; the bridge is not taken down
            // under it. A hold held when they were noted made this follow busy then (FollowCore), so
            // the count alone decides. Decided under the lock every hold is taken under, so a hold and
            // this cannot pass each other: work that asks after this finds no service to hold.
            heldMeanwhile = _holdsTaken != holdsTaken;
            if (!heldMeanwhile)
            {
                // The gate answers null from here until the new service is listening, which is what
                // makes the Remodel tab refuse a run rather than start one against a pipe that is
                // closing. `_starting` is already ours.
                _service = null;
            }
        }

        if (heldMeanwhile)
        {
            // Owed, and asked again a poll later, afresh: by then the work holds the bridge still,
            // or the busy question sees what it began.
            LogSkipped(attached, switchedTo);
            Defer(owed);
            return;
        }

        Stop(attached);

        // Inline: this is the scheduled thread, which is the one StartCore is owed.
        StartCore();
    }

    /// <summary>
    /// Owner decision 152A: a look again at a follow that is owed, on the thread <c>later</c> or
    /// the schedule ran it on. It claims <c>_starting</c> as a switch's follow does, so it never
    /// runs beside a start or a follow - the work in flight looks again itself when it ends - and
    /// asks nothing when nothing is owed any more, the gate is disposed or nothing is listening.
    /// Never throws: it runs on a thread no caller waits on.
    /// </summary>
    private void LookAgain()
    {
        try
        {
            IToolService attached;
            lock (_lock)
            {
                _asking = false;
                if (_disposed || _owed == Owed.Nothing || _starting || _service == null)
                {
                    return;
                }

                attached = _service;
                _starting = true;
            }

            FollowCore(attached, switchedTo: null);
        }
        catch (Exception failure)
        {
            ClearStarting();
            _report("The SwReview tool service could not follow the active document.", failure);
        }
    }

    /// <summary>
    /// Work in flight - a start or a follow - is over: <c>_starting</c> is let go, and a follow
    /// owed meanwhile is looked at now rather than a poll later (owner decision 152A).
    /// </summary>
    private void Settle()
    {
        bool look;
        lock (_lock)
        {
            _starting = false;
            look = !_disposed && _owed != Owed.Nothing && !_asking && _service != null;
            if (look)
            {
                _asking = true;
            }
        }

        if (look)
        {
            Ask(_schedule, LookAgain);
        }
    }

    /// <summary>
    /// Work holds the bridge (owner decision 152A): <c>_starting</c> is let go, the follow is owed as
    /// what it was for, and it is asked again a poll later - one look waiting at a time.
    /// </summary>
    private void Defer(Owed owed)
    {
        bool look;
        lock (_lock)
        {
            _starting = false;
            Owe(owed);
            look = !_disposed && !_asking;
            if (look)
            {
                _asking = true;
            }
        }

        if (look)
        {
            Ask(_later, LookAgain);
        }
    }

    /// <summary>Hands a look to <paramref name="where"/>; one that cannot be handed over is said, and none is left waiting.</summary>
    private void Ask(Action<Action> where, Action look)
    {
        try
        {
            where(look);
        }
        catch (Exception failure)
        {
            lock (_lock)
            {
                _asking = false;
            }

            _report("The SwReview tool service could not be scheduled.", failure);
        }
    }

    /// <summary>Owes <paramref name="owed"/> at least: the larger debt covers the smaller. Under <see cref="_lock"/>.</summary>
    private void Owe(Owed owed)
    {
        if (owed > _owed)
        {
            _owed = owed;
        }
    }

    /// <summary>What is owed, taken: nothing is owed after it. Under <see cref="_lock"/>.</summary>
    private Owed Take()
    {
        Owed owed = _owed;
        _owed = Owed.Nothing;
        return owed;
    }

    private void ClearStarting()
    {
        lock (_lock)
        {
            _starting = false;
        }
    }

    /// <summary>Stops the tool service. Safe to call twice, and from any thread.</summary>
    public void Dispose()
    {
        IToolService? service;
        lock (_lock)
        {
            _disposed = true;
            _owed = Owed.Nothing;
            service = _service;
            _service = null;
        }

        Stop(service);
    }

    private void StartCore()
    {
        IToolService service;
        try
        {
            lock (_lock)
            {
                // Owner decision 152A: this start attaches to what is active when it runs, as it is,
                // so a follow owed before this reading - a switch's or a review's - is made by it, and
                // one asked after it is owed afresh.
                Take();
            }

            PageDocument? document = _activeDocument();
            if (document == null)
            {
                // Nothing open, which is an ordinary state and not worth a line: the pane asks
                // again on every ActiveDocChangeNotify.
                ClearStarting();
                return;
            }

            if (!document.IsAttachable)
            {
                // A drawing. Attaching to one throws, and this method turns a throw into a log
                // line nobody reads, so it is refused before the attempt and said out loud.
                ClearStarting();
                _report(SkippedMessage(document.Path), null);
                return;
            }

            service = _start();
        }
        catch (Exception failure)
        {
            ClearStarting();
            _report("The SwReview tool service did not start.", failure);
            return;
        }

        bool abandoned;
        bool look;
        lock (_lock)
        {
            _starting = false;
            abandoned = _disposed;
            if (!abandoned)
            {
                _service = service;
            }

            // Owner decision 152A: a switch that landed after this start read the active document
            // is looked at once the service is published, not dropped.
            look = !abandoned && _owed != Owed.Nothing && !_asking;
            if (look)
            {
                _asking = true;
            }
        }

        if (abandoned)
        {
            // The add-in unloaded while the attach was still on the application thread. A pipe
            // listening into a SOLIDWORKS with no add-in is worse than no tool service at all.
            Stop(service);
            return;
        }

        try
        {
            _publish(service);
        }
        catch (Exception failure)
        {
            // The host is listening either way; what failed is the handover to the backend.
            _report("The SwReview tool service could not be given to the review backend.", failure);
        }

        if (look)
        {
            Ask(_schedule, LookAgain);
        }
    }

    /// <summary>
    /// Owner decision 152A: whether <paramref name="service"/> is attached to
    /// <paramref name="document"/>, by the rule of what is owed. A switch's follow is made as at the
    /// switch, by <see cref="SameDocument"/> - the path, canonically and ignoring case - so a
    /// configuration switch re-attaches nothing wherever it lands (004, decision 22A; the 152A
    /// review's N3). A review's request is made by the review's own rule,
    /// <see cref="PageDocument.IsSameDocument(PageDocument)"/> - the path ignoring case and the
    /// configuration exactly - so that a document the attach spelled otherwise, which the review
    /// refuses, is followed rather than called the same (the 152A review's R3).
    /// </summary>
    private static bool Serves(IToolService service, PageDocument document, Owed owed) =>
        owed == Owed.Configuration
            ? document.IsSameDocument(service.DocumentPath, service.Configuration)
            : SameDocument(service.DocumentPath, document.Path);

    /// <summary>
    /// Whether a path names a document a scope can be attached to: the rule
    /// <see cref="PageDocument.IsAttachable"/> states, asked of a bare path because
    /// <c>ActiveDocChangeNotify</c> is what hands <see cref="FollowDocument"/> one. Built rather
    /// than restated so there is one extension table in the add-in, not two.
    /// </summary>
    private static bool Attachable(string activePath) =>
        new PageDocument(activePath, null).IsAttachable;

    /// <summary>
    /// The one line a document that is not attached to gets: which document, why, and what to
    /// open instead. Shared by both entry points, because the engineer's question is the same
    /// whether the drawing was open at add-in load or opened later - "why are the tools off?".
    /// </summary>
    private static string SkippedMessage(string documentPath) =>
        "The SwReview tool service is not attaching to '" + documentPath
        + "': a drawing has no configuration to attach to. Open the part or assembly it "
        + "documents.";

    /// <summary>
    /// Whether two paths name the same document. Canonical because SOLIDWORKS hands back
    /// whatever it was opened with, case-insensitive because Windows is; an
    /// <see cref="Path.GetFullPath(string)"/> that throws - a path with a character the
    /// filesystem does not allow - leaves the raw strings to be compared rather than deciding
    /// the documents differ, because "differ" is the answer that restarts the service.
    /// </summary>
    private static bool SameDocument(string attached, string active) =>
        string.Equals(Canonical(attached), Canonical(active), StringComparison.OrdinalIgnoreCase);

    private static string Canonical(string path)
    {
        try
        {
            return Path.GetFullPath(path).TrimEnd('\\', '/');
        }
        catch (Exception)
        {
            return path.Trim().TrimEnd('\\', '/');
        }
    }

    private static void Log(IToolService service, string line)
    {
        try
        {
            service.WriteLog(line);
        }
        catch (Exception)
        {
            // A log that cannot be written must not fail a COM callback.
        }
    }

    private void Stop(IToolService? service)
    {
        if (service == null)
        {
            return;
        }

        // Un-published before it is closed, and from here rather than from each of the three
        // callers, so the invariant is one sentence: what is published is what is listening. A
        // `POST /sessions` that goes out carrying a pipe this method has already closed hands
        // the backend a bridge whose every command fails, where a null bridge makes the Python
        // side fall back to its own attach - which works.
        try
        {
            _publish(null);
        }
        catch (Exception failure)
        {
            _report("The SwReview tool service could not be withdrawn from the review backend.", failure);
        }

        try
        {
            service.Dispose();
        }
        catch (Exception failure)
        {
            _report("The SwReview tool service did not stop cleanly.", failure);
        }
        finally
        {
            try
            {
                _afterStopped(service);
            }
            catch (Exception failure)
            {
                _report("The pane could not be told the SwReview tool service stopped.", failure);
            }
        }
    }
}
