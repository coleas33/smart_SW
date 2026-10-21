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
    /// Owner decision 157A: the gate a Standards check begins through, after every refusal that needs no call
    /// (<see cref="CheckPaneHostOptions.BeginCheck"/>). The add-in answers it through the review host. By default
    /// there is no restart to wait for, and the step runs at once.
    /// </summary>
    public Func<Action, BackendRequestException?> BeginCheck { get; set; } = begin =>
    {
        begin();
        return null;
    };

    /// <summary>
    /// Owner decision 157A: whether a settings restart stands before a check, read only to tell the page so
    /// (<see cref="CheckPaneHostOptions.RestartAhead"/>). By default none does.
    /// </summary>
    public Func<bool> RestartAhead { get; set; } = () => false;

    /// <summary>
    /// Owner decision 157A: how long a check handed to the page holds the restart back waiting for the page's
    /// evaluation call (<see cref="CheckPaneHostOptions.HandOverLimit"/>), taken when the host is built.
    /// </summary>
    public TimeSpan HandOverLimit { get; set; } = CheckPaneHostOptions.DefaultHandOverLimit;

    /// <summary>The clock the <see cref="HandOverLimit"/> is measured by (<see cref="CheckPaneHostOptions.Clock"/>).</summary>
    public Func<TimeSpan> Clock { get; set; } = CheckPaneHostOptions.MonotonicClock;
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
/// What it does own is the order of one `standards.start`, and it is not negotiable. Every
/// refusal comes first, the profile check among them, so a run with nothing to grade against
/// leaves no folder behind for the page to render as an empty run. The run folder is created
/// before the dump because the dump writes into it. The folder is registered before the reply,
/// so a `POST /checks/standards` the page sends the instant it sees `standards.extracted`
/// resolves ids through the right folder. Since owner decision 157A the run begins through the
/// review host's gate once every refusal that needs no call is behind it, reads the run root and
/// the document again once the gate is passed, and holds a settings restart back until the page's
/// evaluation of it has been answered (<see cref="CheckPaneHost.BeginCheck"/>).
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
            BeginCheck = begin => options.BeginCheck(begin),
            RestartAhead = () => options.RestartAhead(),
            HandOverLimit = options.HandOverLimit,
            Clock = () => options.Clock(),
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
    private void Start(string? id)
    {
        PaneActions actions = _pane.Actions;

        // Owner decision 154A: first - the run's folder is made under the run root and handed to the backend,
        // which refuses one on a share - in this tab's words, which its page shows whole. Read with 153A's record:
        // none while a start of the backend under way would bring another into force. Read again once the gate is
        // passed, below, since the gate can make a restart that moves it (owner decision 157A).
        string? judged = _options.RunRootForANewRun();
        if (judged == null)
        {
            actions.SendRunRootMoving(id, NothingChecked, PressAgain);
            return;
        }

        if (actions.RefusedRunRoot(
                id, judged, _options.RunRootProbe, NothingChecked, RunRootRule.InSettingsOnTheReviewTab, PressAgain))
        {
            return;
        }

        PageDocument? document = _options.CurrentDocument();
        if (document == null)
        {
            actions.SendError(
                id,
                "NoDocument",
                "open the part, assembly or drawing you want graded in SOLIDWORKS first: the "
                + "checks are read from the active document.",
                retryable: true);
            return;
        }

        if (_options.Dump == null)
        {
            actions.SendError(
                id,
                "NotAttached",
                "the add-in is not attached to a SOLIDWORKS session, so nothing can be extracted.",
                retryable: true);
            return;
        }

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
            return;
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
            return;
        }

        // Before the run folder and before the dump: with no profile there is nothing to grade
        // against, and a folder left behind would render as an empty run the engineer has to
        // work out the meaning of (FR-002).
        string? profileFailure = ProfileFailure();
        if (profileFailure != null)
        {
            actions.SendError(id, "NoProfile", profileFailure, retryable: true);
            return;
        }

        // Owner decision 157A: a check holds a settings restart back, as a remodel run does. After every refusal that
        // needs no call, a restart that waits is made first - or the one being made waited for - and the check takes
        // its hold under that restart's own lock, so no restart can begin under it; or the press is refused, saying
        // why. From here every way out but the hand-over of the run to the page lets the hold go.
        if (!_pane.BeginCheck(id, CheckAfterRestartMessage))
        {
            return;
        }

        bool handedOver = false;
        try
        {
            // The gate can have made a restart that brought another run root into force: judged again before
            // anything is made under it (the reviews of decision 154A, N8).
            string? runRoot = actions.RunRootToUse(
                id,
                judged,
                _options.RunRootForANewRun(),
                _options.RunRootProbe,
                NothingChecked,
                RunRootRule.InSettingsOnTheReviewTab,
                PressAgain);
            if (runRoot == null)
            {
                return;
            }

            // ...and it can have waited through a restart for seconds, in which the engineer can make another
            // document active, which the dump would read: read again, and a check of another document than the one
            // pressed for is refused, before anything is made.
            if (!document.IsSameDocument(_options.CurrentDocument()))
            {
                actions.SendError(id, "DocumentChanged", DocumentChangedMessage, retryable: true);
                return;
            }

            string runDirectory;
            try
            {
                runDirectory = RunFolders.CreateForStandards(
                    runRoot, document.Path, _options.Now());
            }
            catch (Exception failure)
            {
                PostStatus("error", failure.Message);
                actions.SendError(
                    id,
                    "RunFolderFailed",
                    $"the standards run folder could not be created under '{runRoot}': "
                    + failure.Message,
                    retryable: false);
                return;
            }

            DumpSummary summary;
            PostStatus(
                "extracting",
                $"Reading {RunFolders.DocumentName(document.Path)}...");
            try
            {
                summary = _options.Dump.Run(
                    runDirectory,
                    message => PostStatus("extracting", message),

                    // The hole, fastener, face and mesh phases are most of a dump's cost and no
                    // standards check reads any of them; the cut-list and drawing phases this
                    // profile adds are what four of the sixteen do read. The package records that
                    // this profile ran, so a thin package is never mistaken for a model with no
                    // holes in it (FR-027).
                    DumpProfile.Standards);
            }
            catch (Exception failure)
            {
                // The folder is left behind on purpose: whatever the dump did write is the evidence
                // for why it stopped (constitution Principle I). It is not registered, because a
                // half-written package must not become the folder Show and the Ask tab read from.
                PostStatus("error", failure.Message);
                actions.SendError(id, "ExtractionFailed", failure.Message, retryable: true);
                return;
            }

            // The reviews of 154A's merge, N6: the extraction took minutes. Since owner decision 157A no restart can
            // move the run root meanwhile while a backend is up - the check holds it back - but a start that brings a
            // backend up where there was none, which nothing holds back (a save's with no backend up, or the add-in's
            // first), can have brought another run root into force. Read again: the run goes on only while its
            // folder is under the run root in force, and is answered here otherwise.
            if (actions.AnsweredForAMovedRunRoot(
                    id, runDirectory, _options.RunRootForANewRun(), "the document was read", NothingChecked, PressAgain))
            {
                return;
            }

            TrackCheck(runDirectory);

            PostStatus(
                "ready",
                (summary.Gaps == 0 ? "Extracted" : $"Extracted with {summary.Gaps} gaps")
                    + DumpSummary.UnexaminedClause(summary.Unexamined)
                    + ". Grading against the profile...");

            // Owner decision 157A: the hold now waits for the page's evaluation of this run, handed over before the
            // page is told, so an evaluation sent the instant it reads this finds it.
            _pane.HandOver(runDirectory);
            handedOver = true;
            actions.Send("standards.extracted", id, new Dictionary<string, object?>
            {
                { "run_dir", runDirectory },
                { "document", document.Path },
                { "configuration", document.Configuration },
                {
                    "counts",
                    new Dictionary<string, object?>
                    {
                        { "documents", summary.Documents },
                        { "features", summary.Features },
                        { "cut_list_items", summary.CutListItems },
                        { "drawing_sheets", summary.DrawingSheets },
                    }
                },
                { "gaps", summary.Gaps },
            });
        }
        finally
        {
            if (!handedOver)
            {
                _pane.EndCheck();
            }
        }
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
