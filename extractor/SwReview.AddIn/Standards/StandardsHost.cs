using System;
using System.Collections.Generic;
using System.IO;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;

namespace SwReview.AddIn.Standards;

/// <summary>Everything <see cref="StandardsHost"/> is given; injected so it is testable headless.</summary>
public sealed class StandardsHostOptions
{
    /// <param name="channel">Where replies and unsolicited messages go.</param>
    /// <param name="runRoot">The run root in force, read fresh: the restart a settings save makes moves it.</param>
    public StandardsHostOptions(IPageChannel channel, Func<string> runRoot)
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
    /// The run root a Standards run's folder is made under, read once to judge it and make the folder (owner
    /// decision 154A, with 153A's record of the settings in force), and again once the extraction is over (the
    /// reviews of 154A's merge, N6): the run root in force, or null while a start of the backend under way would
    /// bring another into force - the backend coming up makes runs only under its own, and may yet fail and leave
    /// the one it would replace - which `standards.start` refuses. The run root in force by default.
    /// </summary>
    public Func<string?> RunRootForANewRun { get; set; }

    /// <summary>
    /// The run root saved in the Review tab's Settings, which the next restart brings into force, or null when no
    /// review host knows it (the reviews of 154A's merge, N4): a start refused for the run root in force while
    /// another is saved says to retry the restart, not to choose a folder again. None by default.
    /// </summary>
    public Func<string?> RunRootSaved { get; set; } = () => null;

    /// <summary>
    /// The backend's endpoint, or null before it is listening. The page calls
    /// `POST /checks/standards` itself with what `init` carries, so this is the whole of the
    /// host's involvement with it.
    /// </summary>
    public Func<BackendEndpoint?> Backend { get; set; } = () => null;

    /// <summary>The open document, asked for fresh each time; SOLIDWORKS owns the answer.</summary>
    public Func<PageDocument?> CurrentDocument { get; set; } = () => null;

    /// <summary>
    /// The configured Standards profile path (`UserSettings.StandardsProfilePath`), or null when
    /// none is configured. Read fresh, because a settings save moves it, and read as a
    /// <b>path</b>: this host never opens the file for its contents (FR-002).
    /// </summary>
    public Func<string?> ProfilePath { get; set; } = () => null;

    /// <summary>
    /// The in-process extractor - the same <see cref="IReviewDump"/> the Review tab runs, asked
    /// for the <see cref="DumpProfile.Standards"/> profile. Null until the add-in is attached to
    /// a SOLIDWORKS session, which is a state the pane really has.
    /// </summary>
    public IReviewDump? Dump { get; set; }

    /// <summary>
    /// Makes the run's folder the pane's latest run (`ReviewHost.TrackCheck`). There is one
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
    /// Owner decision 157A: how a Standards check holds a settings restart back - the gate it begins through, the word
    /// on a restart ahead, the hand-over's limit and its clock (<see cref="CheckHoldOptions"/>) - handed on whole to
    /// the check pane. The add-in sets the gate and the word through the review host. No restart to wait for, by
    /// default.
    /// </summary>
    public CheckHoldOptions Hold { get; } = new CheckHoldOptions();
}

/// <summary>
/// The Standards page's other half: `ready`, `standards.start`, and the four rows every pane
/// host shares, delegated to <see cref="PaneActions"/> (`contracts/standards-check.md`
/// sections 2 and 3).
///
/// Everything except `standards.start` is <see cref="CheckPaneHost"/>'s - the envelope, `ready`
/// and its `init`, the check records, the newest-run scan, the unsolicited messages and the
/// four shared rows. The collaborator is <b>held, not inherited</b>, exactly as
/// <see cref="Review.ReviewHost"/>'s sibling <c>ModelCheckHost</c> holds it (plan.md Structure
/// Decision 3): this host keeps its own start verb, its own refusals and its own options, and
/// nothing about a backend chat or a re-modeler's seat is dragged in by a base class.
///
/// What it does not do is most of the design:
///
/// <b>It evaluates nothing.</b> The page calls `POST /checks/standards` itself, with the token,
/// the origin and the `profile_path` it received in `init`. There is exactly one
/// no-language-model evaluation entry point and it is in Python (FR-024); a host that called
/// the checks would be a second one, and a sixteen-row result over every document a drawing
/// reaches is not something to send over the `postMessage` channel either.
///
/// <b>It never reads the profile.</b> It checks that a path is configured and that the file at
/// it can be opened, and stops there. The schema is expressed in exactly one place -
/// `checks/standards/profile.py` - and a host that validated it would be a second expression of
/// it to keep in step, which is the drift this design exists to avoid (FR-002). No profile
/// value ever enters this process.
///
/// <b>It registers no tool and writes to no document.</b>
///
/// <b>It does not own "the pane's latest run".</b> It creates the run folder and the
/// collaborator hands it to <see cref="StandardsHostOptions.RegisterLatestRun"/>, so
/// `entity.show` resolves `document_id` through the package that was just written and the Ask
/// tab opens in the same place.
///
/// What it does own is the first half of one `standards.start`: its refusals. Every refusal
/// comes first, the profile check among them, so a run with nothing to grade against leaves no
/// folder behind for the page to render as an empty run. Once they are behind it the start is
/// the collaborator's, written once for both check tabs in this tab's words
/// (<see cref="CheckPaneHost.RunCheck"/>, the reviews of owner decision 157A): the run begins
/// through the review host's gate, reads the run root and the document again once the gate is
/// passed, creates the run folder before the dump because the dump writes into it, registers the
/// folder before the reply, so a `POST /checks/standards` the page sends the instant it sees
/// `standards.extracted` resolves ids through the right folder, and holds a settings restart back
/// until the page's evaluation of it has been answered.
///
/// Threading: <see cref="Receive"/> is not re-entrant, and must not run on the SOLIDWORKS UI
/// thread - a dump occupies the application thread for as long as it takes. The caller delivers
/// page messages one at a time, as it already does for every other pane.
/// </summary>
public sealed class StandardsHost : IDisposable
{
    /// <summary>The one message type this host answers itself.</summary>
    private const string StartType = "standards.start";

    /// <summary>What a refused `standards.start` did not do, in its words (owner decision 154A).</summary>
    private const string NothingChecked = "nothing was checked";

    /// <summary>What a refused `standards.start` says to do once the cause is gone (owner decision 154A).</summary>
    private const string PressAgain = "press Standards check again";

    /// <summary>The setting a refusal names, because it is what the engineer has to change.</summary>
    private const string ProfileSetting = "StandardsProfilePath";

    /// <summary>
    /// What the page is told before the gate when a settings restart stands before the press (owner decision 157A),
    /// posted as `status {stage: "backend_starting"}`.
    /// </summary>
    public const string CheckAfterRestartMessage = PaneActions.WaitingForTheRestart + "reading the document...";

    /// <summary>
    /// What a `standards.start` whose document changed while its gate waited through a settings restart is refused
    /// with, `DocumentChanged` (owner decision 157A): no path, and the way on.
    /// </summary>
    public const string DocumentChangedMessage =
        "The active document or its configuration changed after Standards check was pressed, so nothing was checked. "
        + "Make the document you want graded the active document and press Standards check again.";

    /// <summary>
    /// The document kinds the sixteen checks are written for. All three are gradable - unlike
    /// the Model check tab, which is part-only - and anything else is refused by name rather
    /// than graded into sixteen out-of-scope rows.
    /// </summary>
    private static readonly string[] GradableKinds = { "part", "assembly", "drawing" };

    private readonly StandardsHostOptions _options;
    private readonly CheckPaneHost _pane;
    private readonly CheckStart _start;

    public StandardsHost(StandardsHostOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));

        // Every accessor is wrapped rather than handed over, so a caller that replaces one
        // after construction still has it read fresh - which is what "a settings save moves the
        // run root" and "the backend started after the pane opened" both depend on.
        _pane = new CheckPaneHost(new CheckPaneHostOptions(
            options.Channel, () => options.RunRoot(), StartType, Start)
        {
            RunRootsInForce = () => options.RunRootsInForce(),
            RunRootSaved = () => options.RunRootSaved(),
            Backend = () => options.Backend(),
            CurrentDocument = () => options.CurrentDocument(),

            // What `init` reads the newest run back by after a restart, from the folder names
            // alone. `-standards` is this tab's own suffix, so a Model check's folder is never
            // offered here (`contracts/standards-check.md` section 4, difference D10).
            LatestCheckSuffix = RunFolders.StandardsSuffix,

            // The page shows which profile is in force and relays the path on its own request.
            // The PATH only: no profile value travels on any message (FR-034).
            ExtraInitFields = () => new[]
            {
                new KeyValuePair<string, object?>(
                    "profile_path", CheckPaneHost.Configured(options.ProfilePath())),
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

        // Owner decision 157A, the reviews: what is this tab's own in a run's start once its refusals are behind it;
        // the start itself is the check pane's, written once for both tabs.
        _start = new CheckStart(
            noDocument: "open the part, assembly or drawing you want graded in SOLIDWORKS first: the "
                + "checks are read from the active document.",
            refuses: Refused,
            dump: () => options.Dump,
            restartFirst: CheckAfterRestartMessage,
            documentChanged: DocumentChangedMessage,
            nothingChecked: NothingChecked,
            pressAgain: PressAgain,
            runRootForANewRun: () => options.RunRootForANewRun(),
            probe: () => options.RunRootProbe,
            createFolder: RunFolders.CreateForStandards,
            folder: "the standards run folder",
            reading: document => $"Reading {document}...",

            // The hole, fastener, face and mesh phases are most of a dump's cost and no standards check reads any of
            // them; the cut-list and drawing phases this profile adds are what four of the sixteen do read. The package
            // records that this profile ran, so a thin package is never mistaken for a model with no holes in it
            // (FR-027).
            profile: DumpProfile.Standards,
            during: "the document was read",
            next: ". Grading against the profile...",
            extractedType: "standards.extracted",
            counts: summary => new Dictionary<string, object?>
            {
                { "documents", summary.Documents },
                { "features", summary.Features },
                { "cut_list_items", summary.CutListItems },
                { "drawing_sheets", summary.DrawingSheets },
            });
    }

    /// <summary>The runs this host made, oldest first.</summary>
    public IReadOnlyList<CheckRecord> Checks => _pane.Checks;

    /// <summary>The newest run this session made, or null before the first one.</summary>
    public CheckRecord? LatestCheck => _pane.LatestCheck;

    /// <summary>Records a run's folder and makes it the pane's latest run.</summary>
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
    /// Whether a Standards check holds a settings restart back (owner decision 157A,
    /// <see cref="CheckPaneHost.CheckInProgress"/>): what the review host's restart reads, under its own lock.
    /// </summary>
    public bool CheckInProgress => _pane.CheckInProgress;

    /// <summary>
    /// The pane's proxy takes over the hold of the check whose run it evaluates, while the evaluation is out (owner
    /// decision 157A, <see cref="CheckPaneHost.HoldEvaluation"/>); null when no check of this tab waits for it.
    /// </summary>
    public IDisposable? HoldEvaluation(string runDirectory) => _pane.HoldEvaluation(runDirectory);

    public void Dispose() => _pane.Dispose();

    // ---- standards.start ------------------------------------------------------------------

    /// <summary>
    /// Press Standards check: refuse what cannot be graded, name and create the run folder, dump
    /// the open document into it with the Standards profile, register the folder as the pane's
    /// latest run, and tell the page where it is. The page does the rest.
    /// </summary>
    private void Start(string? id) => _pane.StartCheck(id, _start);

    /// <summary>
    /// This tab's own refusals of the active document, after the shared ones (<see cref="CheckPaneHost.StartCheck"/>):
    /// one never saved, a kind not graded, and no profile to grade against. Answers whether it refused the press,
    /// having sent the refusal.
    /// </summary>
    private bool Refused(string? id, PageDocument document)
    {
        PaneActions actions = _pane.Actions;
        if (string.IsNullOrWhiteSpace(document.Path))
        {
            // No path means no library prefix to match and no file name to match the
            // part-number pattern against, so most of the sixteen checks would have nothing to
            // read. The macro is silent in exactly this case, because it decides the document
            // kind from the last three characters of a path that is empty.
            actions.SendError(
                id,
                "NeverSaved",
                "this document has never been saved, so it has no file name or folder for the "
                + "library and part-number checks to read. Save it and press Standards again.",
                retryable: true);
            return true;
        }

        if (Array.IndexOf(GradableKinds, document.Kind) < 0)
        {
            actions.SendError(
                id,
                "UnsupportedKind",
                "the Standards check grades a part, an assembly or a drawing, and the active "
                + "document is "
                + (document.Kind == null ? "none of those" : "a " + document.Kind)

                // Named through the same cleaner the run folder is named by, which parses by
                // hand: `Path.GetFileName` throws on invalid path characters in .NET Framework,
                // and a strange path must not turn a refusal into a crash.
                + " ('" + RunFolders.DocumentName(document.Path) + "').",
                retryable: true);
            return true;
        }

        // Before the run folder and before the dump: with no profile there is nothing to grade
        // against, and a folder left behind would render as an empty run the engineer has to
        // work out the meaning of (FR-002).
        string? profileFailure = ProfileFailure();
        if (profileFailure != null)
        {
            actions.SendError(id, "NoProfile", profileFailure, retryable: true);
            return true;
        }

        return false;
    }

    /// <summary>
    /// Why the configured profile cannot be used, or null when it can be.
    ///
    /// <b>Configured and readable, and nothing else.</b> The file is opened and closed without
    /// a byte of it being read: that answers "is there a file here this process can open" -
    /// which covers a path that is not there, a directory where the file should be, an ACL and
    /// an exclusive lock - without this side of the wall learning anything about the schema
    /// (FR-002). Whether the contents are a valid profile is the backend's answer, and it names
    /// the field.
    /// </summary>
    private string? ProfileFailure()
    {
        string? path = CheckPaneHost.Configured(_options.ProfilePath());
        if (path == null)
        {
            return $"no standards profile is configured: set `{ProfileSetting}` to the profile "
                + "YAML on this workstation.";
        }

        try
        {
            using (File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                return null;
            }
        }
        catch (Exception failure)
        {
            return $"the standards profile at '{path}' could not be opened ({failure.Message}). "
                + $"Check `{ProfileSetting}`.";
        }
    }
}
