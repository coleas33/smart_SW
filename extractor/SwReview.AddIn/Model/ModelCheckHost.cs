using System;
using System.Collections.Generic;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;

namespace SwReview.AddIn.Model;

/// <summary>Everything <see cref="ModelCheckHost"/> is given; injected so it is testable headless.</summary>
public sealed class ModelCheckHostOptions
{
    /// <param name="channel">Where replies and unsolicited messages go.</param>
    /// <param name="runRoot">The run root in force, read fresh: the restart a settings save makes moves it.</param>
    public ModelCheckHostOptions(IPageChannel channel, Func<string> runRoot)
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
    /// The run root a check's folder is made under, read once to judge it and make the folder (owner decision 154A,
    /// with 153A's record of the settings in force), and again once the extraction is over (the reviews of 154A's
    /// merge, N6): the run root in force, or null while a start of the backend under way would bring another into
    /// force - the backend coming up makes runs only under its own, and may yet fail and leave the one it would
    /// replace - which `check.start` refuses. The run root in force by default.
    /// </summary>
    public Func<string?> RunRootForANewRun { get; set; }

    /// <summary>
    /// The run root saved in the Review tab's Settings, which the next restart brings into force, or null when no
    /// review host knows it (the reviews of 154A's merge, N4): a start refused for the run root in force while
    /// another is saved says to retry the restart, not to choose a folder again. None by default.
    /// </summary>
    public Func<string?> RunRootSaved { get; set; } = () => null;

    /// <summary>
    /// The backend's endpoint, or null before it is listening. The page calls the check routes
    /// itself with what `init` carries, so this is the whole of the host's involvement with it.
    /// </summary>
    public Func<BackendEndpoint?> Backend { get; set; } = () => null;

    /// <summary>A failed start with no backend up, remembered by the Review host (owner decision 160A).</summary>
    public Func<bool> BackendStartFailed { get; set; } = () => false;

    /// <summary>The open document, asked for fresh each time; SOLIDWORKS owns the answer.</summary>
    public Func<PageDocument?> CurrentDocument { get; set; } = () => null;

    /// <summary>
    /// The configured standards profile path (`UserSettings.StandardsProfilePath`, the setting the
    /// Review tab sends with a review), or null when none is configured. Read fresh, because a
    /// settings save moves it, and handed to the page as a <b>path</b> in `init`: the page relays it
    /// on `POST /checks/rms`, so the body can say the open part looks bought and why it is graded
    /// anyway (feature 013 T150, FR-008). This host never opens the file.
    /// </summary>
    public Func<string?> ProfilePath { get; set; } = () => null;

    /// <summary>
    /// The in-process extractor - the same <see cref="IReviewDump"/> the Review tab runs, asked
    /// for the <see cref="DumpProfile.ModelCheck"/> profile. Null until the add-in is attached
    /// to a SOLIDWORKS session, which is a state the pane really has.
    /// </summary>
    public IReviewDump? Dump { get; set; }

    /// <summary>
    /// Makes the check's folder the pane's latest run (`ReviewHost.TrackCheck`). There is one
    /// answer to "which folder is the pane looking at" and it is not this host's to keep.
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

    /// <summary>
    /// What the run root rule reads of Windows (owner decision 154A): a share, a mapped or substituted drive,
    /// a link. Windows itself by default; injected so a test fakes each without making one.
    /// </summary>
    public IRunRootProbe RunRootProbe { get; set; } = Native.WindowsRunRootProbe.Instance;

    /// <summary>
    /// Owner decision 157A: how a Model check holds a settings restart back - the gate it begins through, the word on
    /// a restart ahead, the hand-over's limit and its clock (<see cref="CheckHoldOptions"/>) - handed on whole to the
    /// check pane. The add-in sets the gate and the word through the review host. No restart to wait for, by default.
    /// </summary>
    public CheckHoldOptions Hold { get; } = new CheckHoldOptions();
}

/// <summary>
/// The Model check page's other half: `ready`, `check.start`, and the four rows every pane host
/// shares, delegated to <see cref="PaneActions"/> (`contracts/model-check.md` sections 2 and 3).
///
/// Everything except `check.start` is <see cref="CheckPaneHost"/>'s - the envelope, `ready` and
/// its `init`, the check records, the unsolicited messages and the four shared rows - because
/// the Standards check tab needs the same plumbing and copying it would be the second largest
/// copy this codebase could make. The collaborator is <b>held, not inherited</b> (plan.md
/// Structure Decision 3, feature 006): a base class over the pane hosts would drag backend chat
/// state into a host that has none, and this host keeps its own start verb, its own refusals and
/// its own options either way. What it no longer keeps is a record type of its own:
/// <see cref="CheckRecord"/> is now <see cref="CheckPaneHost"/>'s and both check hosts share it,
/// which is a deviation from that decision's wording and is written down there.
///
/// What it does not do is most of the design:
///
/// <b>It evaluates nothing.</b> The page calls `POST /checks/rms` itself, with the token and
/// origin it received in `init`, the same way the Review page already calls the message,
/// evidence and disposition routes. There is exactly one no-language-model evaluation entry
/// point and it is in Python (FR-024); a host that called the rules would be a second one, and
/// keeping a potentially large result off the `postMessage` channel is a second reason.
///
/// <b>It registers no tool and writes to no document</b> (FR-031).
///
/// <b>It does not own "the pane's latest run".</b> It creates the check folder and the
/// collaborator hands it to <see cref="ModelCheckHostOptions.RegisterLatestRun"/>, so
/// `entity.show` resolves `document_id` through the package that was just written and the Ask
/// tab opens in the same place (FR-028).
///
/// What it does own is the first half of one `check.start`: its refusals, which come first
/// because a dump is SOLIDWORKS time. Once they are behind it the start is the collaborator's,
/// written once for both check tabs in this tab's words (<see cref="CheckPaneHost.RunCheck"/>,
/// the reviews of owner decision 157A): the check begins through the review host's gate, reads
/// the run root and the document again once the gate is passed, creates the run folder before
/// the dump because the dump writes into it, registers the folder before the reply, so a
/// `POST /checks/rms` the page sends the instant it sees `check.extracted` resolves ids through
/// the right folder, and holds a settings restart back until the page's evaluation of it has
/// been answered.
///
/// Threading: <see cref="Receive"/> is not re-entrant, and must not run on the SOLIDWORKS UI
/// thread - a dump occupies the application thread for as long as it takes. The caller
/// delivers page messages one at a time, as it already does for the Review page.
/// </summary>
public sealed class ModelCheckHost : IDisposable
{
    /// <summary>The only scope this increment evaluates (`contracts/model-check.md`).</summary>
    private const string PartKind = "part";

    /// <summary>The one message type this host answers itself.</summary>
    private const string StartType = "check.start";

    /// <summary>What a refused `check.start` did not do, in its words (owner decision 154A).</summary>
    private const string NothingChecked = "nothing was checked";

    /// <summary>What a refused `check.start` says to do once the cause is gone (owner decision 154A).</summary>
    private const string PressAgain = "press Model check again";

    /// <summary>
    /// What the page is told before the gate when a settings restart stands before the press (owner decision 157A),
    /// posted as `status {stage: "backend_starting"}`.
    /// </summary>
    public const string CheckAfterRestartMessage = PaneActions.WaitingForTheRestart + "reading the feature tree...";

    /// <summary>
    /// What a `check.start` whose document changed while its gate waited through a settings restart is refused with,
    /// `DocumentChanged` (owner decision 157A): no path, and the way on.
    /// </summary>
    public const string DocumentChangedMessage =
        "The active document or its configuration changed after Model check was pressed, so nothing was checked. "
        + "Make the part you want checked the active document and press Model check again.";

    private readonly ModelCheckHostOptions _options;
    private readonly CheckPaneHost _pane;
    private readonly CheckStart _start;

    public ModelCheckHost(ModelCheckHostOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));

        // Every accessor is wrapped rather than handed over, so a caller that replaces one
        // after construction still has it read fresh - which is what "a settings save moves
        // the run root" and "the backend started after the pane opened" both depend on.
        _pane = new CheckPaneHost(new CheckPaneHostOptions(
            options.Channel, () => options.RunRoot(), StartType, StartCheck)
        {
            RunRootsInForce = () => options.RunRootsInForce(),
            RunRootSaved = () => options.RunRootSaved(),
            RunRootProbe = () => options.RunRootProbe,
            Backend = () => options.Backend(),
            BackendStartFailed = () => options.BackendStartFailed(),
            CurrentDocument = () => options.CurrentDocument(),

            // What `init` reads the newest check back by after a restart, from the folder names
            // alone. `-check` is this tab's own suffix, so the Standards tab's runs are never
            // answered with here and this tab's are never answered with there
            // (`contracts/standards-check.md` section 4).
            LatestCheckSuffix = RunFolders.CheckSuffix,

            // The path only, as the Standards tab's `profile_path`: no profile value travels on any
            // message (feature 013 T150; contracts/model-check.md section 2).
            ExtraInitFields = () => new[]
            {
                new KeyValuePair<string, object?>(
                    "standards_profile", CheckPaneHost.Configured(options.ProfilePath())),
            },
            RegisterLatestRun = directory => options.RegisterLatestRun(directory),
            EntityResolver = () => options.EntityResolver(),
            Opener = () => options.Opener(),
            LogFolder = () => options.LogFolder(),
            Now = () => options.Now(),
            Secrets = () => options.Secrets(),

            // Owner decision 157A: a check holds a settings restart back, beginning through the review host's gate.
            Hold = options.Hold,
        });

        // Owner decision 157A, the reviews: what is this tab's own in a check's start once its refusals are behind it;
        // the start itself is the check pane's, written once for both tabs.
        _start = new CheckStart(
            noDocument: "open the part you want checked in SOLIDWORKS first: the feature tree is read "
                + "from the active document.",
            refuses: Refused,
            dump: () => options.Dump,
            restartFirst: CheckAfterRestartMessage,
            documentChanged: DocumentChangedMessage,
            nothingChecked: NothingChecked,
            pressAgain: PressAgain,
            runRootForANewRun: () => options.RunRootForANewRun(),
            createFolder: RunFolders.CreateForCheck,
            folder: "the check folder",
            reading: document => $"Reading the feature tree of {document}...",

            // The hole, fastener, face and mesh phases are most of a dump's cost and no RMS rule reads any of them.
            // The package records that this profile ran, so a thin package is never mistaken for a model with no
            // holes in it (FR-022, RK-19).
            profile: DumpProfile.ModelCheck,
            during: "the feature tree was read",
            next: ". Checking the model...",
            extractedType: "check.extracted",
            counts: summary => new Dictionary<string, object?>
            {
                { "documents", summary.Documents },
                { "features", summary.Features },
                { "equations", summary.Equations },
            });
    }

    /// <summary>The checks this host ran, oldest first.</summary>
    public IReadOnlyList<CheckRecord> Checks => _pane.Checks;

    /// <summary>The newest check, or null before the first one.</summary>
    public CheckRecord? LatestCheck => _pane.LatestCheck;

    /// <summary>Records a check's folder and makes it the pane's latest run.</summary>
    public CheckRecord TrackCheck(string runDirectory) => _pane.TrackCheck(runDirectory);

    /// <summary>The record for <paramref name="checkId"/>, or null.</summary>
    public CheckRecord? FindCheck(string checkId) => _pane.FindCheck(checkId);

    /// <summary>Handles one message from the page. Never throws.</summary>
    public void Receive(string json) => _pane.Receive(json);

    /// <summary>Sends an unsolicited message (`status`, `document.changed`, `backend.stopped`).</summary>
    public void Post(string type, object? payload) => _pane.Post(type, payload);

    /// <summary>Posts one `status`, with every secret masked out of it (FR-015).</summary>
    public void PostStatus(string stage, string message) => _pane.PostStatus(stage, message);

    /// <summary><see cref="PostStatus(string, string)"/>, marked as the add-in's own word on the backend when <paramref name="lifecycle"/> (owner decision 145A).</summary>
    public void PostStatus(string stage, string message, bool lifecycle) => _pane.PostStatus(stage, message, lifecycle);

    /// <summary>Tells the page which document the pane is looking at now, or that there is none.</summary>
    public void DocumentChanged() => _pane.DocumentChanged();

    /// <summary>Tells the page the backend was restarted with saved settings (owner decision 145A).</summary>
    public void BackendRestarted() => _pane.BackendRestarted();

    /// <summary>
    /// Whether a Model check holds a settings restart back (owner decision 157A,
    /// <see cref="CheckPaneHost.CheckInProgress"/>): what the review host's restart reads, under its own lock.
    /// </summary>
    public bool CheckInProgress => _pane.CheckInProgress;

    /// <summary>
    /// The pane's proxy takes over the hold of the check whose run it evaluates, while the evaluation is out (owner
    /// decision 157A, <see cref="CheckPaneHost.HoldEvaluation"/>); null when no check of this tab waits for it.
    /// </summary>
    public IDisposable? HoldEvaluation(string runDirectory, string? token) => _pane.HoldEvaluation(runDirectory, token);

    public void Dispose() => _pane.Dispose();

    // ---- check.start --------------------------------------------------------------------

    /// <summary>
    /// Press Model check: refuse what cannot be checked, name and create the check run folder,
    /// dump the open part into it with the reduced profile, register the folder as the pane's
    /// latest run, and tell the page where it is. The page does the rest.
    /// </summary>
    private void StartCheck(string? id) => _pane.StartCheck(id, _start);

    /// <summary>
    /// This tab's own refusal of the active document, after the shared ones (<see cref="CheckPaneHost.StartCheck"/>):
    /// a document that is not a part. Answers whether it refused the press, having sent the refusal.
    /// </summary>
    private bool Refused(string? id, PageDocument document)
    {
        if (string.Equals(document.Kind, PartKind, StringComparison.Ordinal))
        {
            return false;
        }

        // The rule family is written about a part's feature tree. An assembly answered with
        // 34 unresolved rules would read as a bad design rather than as a scope this
        // increment does not cover, so the refusal names the scope instead.
        _pane.Actions.SendError(
            id,
            "NotAPart",
            "the Model check reads a part's feature tree, and the active document is "
            + (document.Kind == null ? "not a SOLIDWORKS part" : "a " + document.Kind)
            + ". Open the part on its own and press Model check again.",
            retryable: true);
        return true;
    }
}
