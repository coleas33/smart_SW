using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using SwReview.AddIn.Model;
using SwReview.AddIn.Native;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.Terminal;
using SwReview.AddIn.ToolService;

// The load path is the part of this add-in no test can reach through its public surface:
// AssemblyRedirect's install state, and the log folder AddInLog writes to (which a test must
// be able to point somewhere else, or `dotnet test` writes into the engineer's real addin.log).
[assembly: System.Runtime.CompilerServices.InternalsVisibleTo("SwReview.AddIn.Tests")]

namespace SwReview.AddIn;

/// <summary>
/// In-process SOLIDWORKS 2024 add-in host (research R1: in-process traversal is 10 to 100x
/// faster than out-of-process COM, and several many-parameter API members fail late-bound).
///
/// It owns the ISldWorks pointer and the Task Pane: the Review tab (the chat page in
/// WebView2, driven by <see cref="ReviewHost"/> over the loopback backend), the Ask tab (the
/// CLI terminal), and the Extract tab's three buttons, all acting on the active document:
/// <b>Extract evidence</b> runs <see cref="PackageWriter"/>, <b>Interference</b> runs
/// <see cref="InterferenceRunner"/> and <b>Capture selection</b> runs
/// <see cref="CaptureService"/>. The latter two append to the package.json that Extract
/// evidence wrote in the same folder, so their results can name its components.
///
/// It also answers the two questions the pane's step strip asks - is a document open, and does
/// this session's run folder hold evidence - because the add-in is the only thing that can:
/// one reads the active document on the application thread, the other looks in the folder the
/// Review or Ask tab is working in.
///
/// Everything the pane adds is behind a guard, and so is the attach itself. SOLIDWORKS loads
/// this add-in in-process, so an exception out of <see cref="ConnectToSW"/> is the session's
/// problem rather than ours: a WebView2 runtime that is not installed leaves the Review tab
/// showing the fallback panel and the Extract tab working, and a backend that will not start
/// is reported in the pane instead of at load. A failure that does reach the top of
/// <see cref="ConnectToSW"/> is answered by SOLIDWORKS clearing the HKCU startup flag and
/// leaves no log anywhere, so each load step reports itself into
/// %LOCALAPPDATA%\SwReview\logs\addin.log instead (docs/addin-load-fix.md).
///
/// Registration (research R12, "Add-in hosting") is one command, from an elevated x64 prompt:
///
///   extractor\tools\register-addin.ps1 [-Configuration Release] [-Unregister]
///
/// It stages SolidWorks.Interop.{sldworks,swconst,swpublished}.dll from the seat's api\redist
/// into the add-in's output folder and then runs
/// "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\regasm.exe" /codebase SwReview.AddIn.dll.
/// The staging is not optional: regasm loads swpublished to reflect over ISwAddin while
/// registering, and this project deliberately does not copy the seat's interops
/// (Private=false), so a plain regasm on a clean build fails with RA0000.
///
/// The [ComRegisterFunction] below writes both the HKLM AddIns keys and
/// HKCU\SOFTWARE\SOLIDWORKS\AddInsStartup\{5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55} = 1 for the
/// account that ran it, so SwReview is already ticked in Tools > Add-ins the next time
/// SOLIDWORKS starts. A check box that is clear there is a load failure, not a step still to
/// do - read %LOCALAPPDATA%\SwReview\logs\addin.log. (The one exception: if the elevated
/// prompt ran as a different account, the flag landed in that account's hive and this one
/// does have to tick the box once.)
///
/// Build x64 and reference the interops from the seat install
/// (C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist) with Embed Interop Types
/// false; the NuGet SolidWorks.Interop packages are community published and are not used.
/// </summary>
[ComVisible(true)]
[Guid(AddInGuid)]
[ClassInterface(ClassInterfaceType.AutoDispatch)]
[ProgId("SwReview.AddIn.SwReviewAddIn")]
public class SwReviewAddIn : ISwAddin
{
    /// <summary>
    /// The add-in identity. It is written into the HKLM AddIns key and must never change
    /// once a workstation has registered it.
    /// </summary>
    public const string AddInGuid = "5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55";

    private const string AddInTitle = "SwReview";

    private const string AddInDescription = "SwReview evidence extractor (read-only)";

    private ISldWorks? _swApp;
    private int _addInCookie;
    private ITaskpaneView? _taskPane;
    private TaskPaneControl? _pane;
    private ActionsPanel? _panel;
    private IApplicationThread? _applicationThread;

    private SldWorks? _events;

    private JobObject? _job;
    private BackendSupervisor? _supervisor;
    private BackendClient? _backend;
    private ReviewHost? _reviewHost;
    private TerminalHost? _terminalHost;
    private ModelCheckHost? _modelCheckHost;
    private RemodelHost? _remodelHost;
    private ToolServiceGate? _toolService;

    /// <summary>
    /// Page messages, one at a time, off the application thread.
    ///
    /// `WebMessageReceived` is raised on the SOLIDWORKS UI thread and
    /// <see cref="ReviewHost.Receive"/> can take seconds - a dump, a backend restart - so the
    /// messages are queued here and drained by one thread: off the UI thread because the pane
    /// must keep painting, and one thread because the host's handlers are not re-entrant
    /// (see <see cref="IPageChannel"/>).
    /// </summary>
    private readonly BlockingCollection<string> _pageMessages = new BlockingCollection<string>();

    private Thread? _pageMessagePump;

    /// <summary>
    /// The Model check page's messages, on a queue and a thread of their own.
    ///
    /// Separate from the Review page's for the reason its handlers are separate: a
    /// `check.start` runs a dump on the application thread and takes seconds, and queueing it
    /// behind - or in front of - a review's messages would make one tab's work wait on the
    /// other's. One thread each, one message at a time each, because neither host is re-entrant.
    /// </summary>
    private readonly BlockingCollection<string> _modelCheckMessages = new BlockingCollection<string>();

    private Thread? _modelCheckPump;

    /// <summary>
    /// The Remodel page's messages, on a queue and a thread of their own.
    ///
    /// Separate for the same reason the Model check page's are, only more so: a
    /// `remodel.start` runs phases B to D to completion, which the feature bounds at twenty
    /// minutes. Queued behind a review's messages it would be twenty minutes in which no other
    /// tab answered; and `remodel.stop` is delivered on this queue, so a run that occupied its
    /// own pump would be a run that cannot be stopped - which is why <see cref="RemodelHost"/>
    /// schedules the run itself off this thread again.
    /// </summary>
    private readonly BlockingCollection<string> _remodelMessages = new BlockingCollection<string>();

    private Thread? _remodelPump;

    /// <summary>The running SOLIDWORKS session, or null while disconnected.</summary>
    public ISldWorks? SwApp => _swApp;

    /// <summary>The callback cookie SOLIDWORKS issued for this add-in instance.</summary>
    public int AddInCookie => _addInCookie;

    /// <summary>
    /// The tool service, as much of it as anything outside this class may see: the pipe name
    /// and the <b>general-chat</b> secret, for the terminal's generated CLI profile (T057), and
    /// the attached document, for its persona text. Null until the pane has started.
    ///
    /// Deliberately not the review secret, which authorizes <c>interference</c> as well: the
    /// CLI can read its own generated profile, so the profile must never be given a secret
    /// wider than the MCP allowlist it ships with (contracts/README.md).
    /// </summary>
    public IToolServiceAccess? ToolService => _toolService;

    /// <summary>
    /// Runs on COM activation, which is ahead of <see cref="ConnectToSW"/> and so ahead of the
    /// first assembly bind the add-in's own code can provoke. That is the only window in which
    /// <see cref="AssemblyRedirect"/> can be installed: the bind it exists to answer happens
    /// inside <c>CreateTaskPane</c>.
    /// </summary>
    static SwReviewAddIn()
    {
        AssemblyRedirect.Install();
        Log("AssemblyRedirect installed.");
    }

    /// <summary>
    /// Called by SOLIDWORKS when the add-in loads. Everything the extractor does runs on
    /// this thread, which is the application STA thread (constitution: all COM calls on one
    /// STA thread).
    /// </summary>
    public bool ConnectToSW(object ThisSW, int Cookie)
    {
        // Three guards rather than one: an add-in that cannot attach has not loaded and says
        // so, a pane that cannot be created must not stop the add-in loading, and a review
        // host that cannot be started must not take the pane's Actions tab with it. No
        // failure may leave ConnectToSW: SOLIDWORKS answers an exception here by clearing the
        // HKCU AddInsStartup flag, so an unguarded throw is a load that reverts its own check
        // box and leaves no explanation anywhere (docs/addin-load-fix.md).
        try
        {
            _swApp = (ISldWorks)ThisSW;
            _addInCookie = Cookie;

            // Required before any callback can be routed back to this add-in.
            _swApp.SetAddinCallbackInfo2(0, this, _addInCookie);

            Log("Attached to SOLIDWORKS.");
        }
        catch (Exception failure)
        {
            Report("The SwReview add-in could not attach to SOLIDWORKS.", failure);
            return false;
        }

        try
        {
            CreateTaskPane();
            Log("Task Pane created.");
        }
        catch (Exception failure)
        {
            Report("The SwReview Task Pane could not be created.", failure);
        }

        try
        {
            StartReviewHost();
            Log("Review host started.");
        }
        catch (Exception failure)
        {
            Report("The SwReview review host could not be started.", failure);
        }

        return true;
    }

    /// <summary>
    /// Called by SOLIDWORKS when the add-in unloads. Release every interop pointer so the
    /// session can shut down cleanly.
    /// </summary>
    public bool DisconnectFromSW()
    {
        // Order matters: stop listening to the page, stop draining it, then stop the child.
        // The job object goes last, so a backend that ignored its shutdown still dies with the
        // handle (T050).
        if (_pane != null)
        {
            _pane.PageMessageReceived -= OnPageMessage;
            _pane.ModelCheckPageMessageReceived -= OnModelCheckPageMessage;
            _pane.RemodelPageMessageReceived -= OnRemodelPageMessage;
        }

        if (_events != null)
        {
            _events.ActiveDocChangeNotify -= OnActiveDocumentChanged;
            _events = null;
        }

        StopPageMessagePump();
        StopModelCheckPump();
        StopRemodelPump();

        // Before the review host, because the tool service is what still holds SOLIDWORKS
        // pointers: the pipe stops listening and the scope is let go while the add-in is still
        // attached. Requests already in flight get the documented `error` (T047).
        _toolService?.Dispose();
        _toolService = null;

        // Before the review host and after the tool service: the terminal's CLI holds a
        // console and the generated profile, and it is stopped rather than left to the job.
        _terminalHost?.Dispose();
        _terminalHost = null;

        // Before the review host, because a check's record is registered on it: the Model
        // check host holds nothing SOLIDWORKS owns, so this is only about the order the two
        // stop answering in.
        _modelCheckHost?.Dispose();
        _modelCheckHost = null;

        // With the Model check host and for its reason: a remodel run registers its folder on
        // the review host, so the two stop answering in this order.
        _remodelHost?.Dispose();
        _remodelHost = null;

        _reviewHost?.Dispose();
        _reviewHost = null;

        _backend?.Dispose();
        _backend = null;
        _supervisor = null;

        _job?.Dispose();
        _job = null;

        if (_panel != null)
        {
            _panel.DumpRequested -= OnDumpRequested;
            _panel.InterferenceRequested -= OnInterferenceRequested;
            _panel.CaptureRequested -= OnCaptureRequested;
            _panel = null;
        }

        if (_pane != null)
        {
            _pane.Dispose();
            _pane = null;
        }

        _applicationThread = null;

        if (_taskPane != null)
        {
            _taskPane.DeleteView();
            Marshal.ReleaseComObject(_taskPane);
            _taskPane = null;
        }

        _swApp = null;
        _addInCookie = 0;

        GC.Collect();
        GC.WaitForPendingFinalizers();
        return true;
    }

    private void CreateTaskPane()
    {
        if (_swApp == null)
        {
            return;
        }

        _taskPane = _swApp.CreateTaskpaneView2(string.Empty, AddInDescription);
        if (_taskPane == null)
        {
            return;
        }

        // The run root is read here rather than from the review host, because the fallback
        // panel shows it and the fallback panel exists precisely when nothing else started.
        SettingsLoadResult loaded = UserSettings.Load(UserSettings.DefaultPath);
        _pane = new TaskPaneControl(new TaskPaneOptions(
            new WebViewEnvironmentFactory(), loaded.Settings.RunRoot)
        {
            // The Ask tab's run-folder rule (pane-host-messages.md): a terminal started
            // after a review belongs in that review's folder, so the CLI's generated profile,
            // its working directory and the evidence it is being asked about are one place.
            CurrentSessionRunDirectory = () => _reviewHost?.LatestSession?.RunDirectory,

            // The two facts the step strip renders. `_pane` is read through the field rather
            // than captured, because these run long after the constructor that assigns it.
            DocumentPresent = () => CurrentDocument() != null,
            EvidencePresent = () => RunFolders.HasEvidence(_pane?.SessionRunDirectory),
        });

        _panel = _pane.Actions;
        _panel.DumpRequested += OnDumpRequested;
        _panel.InterferenceRequested += OnInterferenceRequested;
        _panel.CaptureRequested += OnCaptureRequested;

        // x64 build, so the 64-bit handle overload is the correct one; the Int32 version
        // truncates the window handle and silently shows nothing.
        _taskPane.DisplayWindowFromHandlex64(_pane.Handle.ToInt64());

        _applicationThread = new PaneApplicationThread(_pane);

        // Not awaited: InitializeAsync never throws, and a WebView2 boot must not hold up the
        // add-in load. Its continuations land back on this thread's message loop.
        _ = _pane.InitializeAsync();
    }

    /// <summary>
    /// Builds the Review tab's host and starts the backend.
    ///
    /// The settings are loaded first - by <see cref="ReviewHost"/>'s constructor - because they
    /// decide everything about the child: which launcher runs it, which run root it will refuse
    /// to write outside of, and which credential goes into its environment. The start itself
    /// runs on a worker thread, because a cold `uv run` takes seconds and this is the SOLIDWORKS
    /// UI thread, and it reports itself to the page as a `status` message either way.
    /// </summary>
    private void StartReviewHost()
    {
        if (_pane == null || _swApp == null || _applicationThread == null)
        {
            return;
        }

        _job = new JobObject();
        _supervisor = new BackendSupervisor(() => _reviewHost != null && _reviewHost.AnyTurnRunning());
        _backend = new BackendClient(_supervisor, ReviewHostOptions.DefaultLogFolder(), _job);

        // The ids on a finding card belong to the run's own package.json, which `review.start`
        // has just written; the resolver is handed lookups over whichever run the pane is
        // currently showing. The two lookups are independent of the tool service.
        var packages = new RunPackageIndex(() => _reviewHost?.LatestSession?.RunDirectory);

        var reviewOptions = new ReviewHostOptions(
            _pane.ReviewChannel, _backend, UserSettings.DefaultPath)
        {
            CurrentDocument = CurrentDocument,
            Dump = new SwReviewDump(_swApp, _applicationThread),
            EntityResolver = new SwEntityResolver(
                _swApp,
                _applicationThread,
                // T048: the tool service's own scope once it is listening, so a Show resolves
                // against the same session the bridge's capture and measure commands run
                // against instead of walking the component tree again per Show. Before it is
                // listening - the Task Pane exists before the first document - the resolver
                // attaches for itself, per Show rather than held: the engineer closes and
                // reopens documents between findings, and a session over a document that is
                // gone selects nothing.
                () => _toolService?.Session
                    ?? SwSession.Attach(_swApp, documentPath: null, configurationName: null),
                packages.DocumentPath,
                packages.ComponentFullPath),
        };

        _reviewHost = new ReviewHost(reviewOptions);
        _toolService = CreateToolServiceGate(reviewOptions);

        StartPageMessagePump();
        _pane.PageMessageReceived += OnPageMessage;

        // The Terminal tab's half of the pane (T060). It subscribes to the Terminal page and
        // drains it on a thread of its own - locating a CLI and probing its tool listing both
        // block for seconds, and this is the SOLIDWORKS UI thread.
        _terminalHost = TerminalHost.Attach(
            _pane,
            _toolService,
            () => _reviewHost?.Settings ?? UserSettings.Defaults(),
            _job,
            // The Ask tab's Extract evidence button runs the review's own extractor, into the
            // run folder the CLI is working in (contracts/pane-host-messages.md).
            reviewOptions.Dump);

        StartModelCheckHost(reviewOptions);
        StartRemodelHost(reviewOptions);

        // The pane follows the engineer: the Review button and the document name track
        // whatever is active, so a review is never started against the document that was open
        // when the pane was created (pane-host-messages.md, `document.changed`).
        _events = _swApp as SldWorks;
        if (_events != null)
        {
            _events.ActiveDocChangeNotify += OnActiveDocumentChanged;
        }

        // SOLIDWORKS usually loads with nothing open, in which case this is a no-op and the
        // document-changed event below starts the tool service instead. It is asked here too
        // because the add-in can be enabled from Tools > Add-ins with an assembly already open,
        // where no ActiveDocChangeNotify is ever raised.
        _toolService.EnsureStarted();

        UserSettings settings = _reviewHost.Settings;
        ResolvedApiKey key = settings.ResolveApiKey();
        ThreadPool.QueueUserWorkItem(_ => StartBackend(settings, key));
    }

    /// <summary>
    /// The Model check tab's host (T083, contracts/model-check.md).
    ///
    /// It shares three things with the Review tab rather than owning copies of them: the same
    /// in-process extractor (asked for the reduced <c>ModelCheck</c> profile), the same entity
    /// resolver, so Show selects the same way on both pages, and the same answer to "which
    /// folder is the pane looking at" - the check registers its own folder through
    /// <see cref="ReviewHost.TrackCheck"/>, which is what makes <c>CurrentSessionRunDirectory</c>
    /// and the package index point at the check the engineer just ran.
    ///
    /// It shares no base class with <see cref="ReviewHost"/>: inheritance would drag settings
    /// and backend state into a host that has neither (plan.md, Structure decision).
    /// </summary>
    private void StartModelCheckHost(ReviewHostOptions reviewOptions)
    {
        if (_pane == null)
        {
            return;
        }

        _modelCheckHost = new ModelCheckHost(new ModelCheckHostOptions(
            _pane.ModelCheckChannel,
            () => (_reviewHost?.Settings ?? UserSettings.Defaults()).RunRoot)
        {
            Backend = () => _backend?.Endpoint,
            CurrentDocument = CurrentDocument,
            Dump = reviewOptions.Dump,
            EntityResolver = () => reviewOptions.EntityResolver,

            // One answer to "which folder is the pane looking at", and it is the review host's
            // to keep: a check that registered itself anywhere else would silently degrade Show
            // to "no full path" for every finding and open the Ask tab in an unrelated folder.
            RegisterLatestRun = runDirectory =>
            {
                _reviewHost?.TrackCheck(runDirectory);
                _pane?.RefreshSteps();
            },

            // The same secret the Review host masks out of its own messages. This host is
            // handed the backend's start-up failures too, and a key-resolution failure is
            // exactly the kind of message that carries one (FR-015).
            Secrets = () => new[]
            {
                (_reviewHost?.Settings ?? UserSettings.Defaults()).ResolveApiKey().Key,
            },
        });

        StartModelCheckPump();
        _pane.ModelCheckPageMessageReceived += OnModelCheckPageMessage;
    }

    private void OnModelCheckPageMessage(object sender, string json)
    {
        try
        {
            _modelCheckMessages.Add(json);
        }
        catch (Exception)
        {
            // The pump is shutting down; the page is about to go with it.
        }
    }

    private void StartModelCheckPump()
    {
        _modelCheckPump = new Thread(() =>
        {
            foreach (string json in _modelCheckMessages.GetConsumingEnumerable())
            {
                try
                {
                    _modelCheckHost?.Receive(json);
                }
                catch (Exception)
                {
                    // ModelCheckHost.Receive answers its own failures; an exception escaping
                    // onto this background thread would take SOLIDWORKS down with it.
                }
            }
        })
        {
            IsBackground = true,
            Name = "swreview-model-check-messages",
        };

        _modelCheckPump.Start();
    }

    private void StopModelCheckPump()
    {
        if (_modelCheckPump == null)
        {
            return;
        }

        try
        {
            _modelCheckMessages.CompleteAdding();
        }
        catch (Exception)
        {
        }

        // Bounded, like the review pump: the thread may be inside a dump, and SOLIDWORKS is
        // not made to wait for it.
        _modelCheckPump.Join(TimeSpan.FromSeconds(2));
        _modelCheckPump = null;
    }

    /// <summary>
    /// The Remodel tab's host (T134f, contracts/pane-remodel-messages.md).
    ///
    /// It shares with the other two tabs exactly what the Model check tab shares - the same
    /// in-process extractor, the same entity resolver, the same answer to "which folder is the
    /// pane looking at" - and adds one thing neither of them has: a pipeline. Everything the
    /// run does to SOLIDWORKS goes through <see cref="BackendRemodelPipeline"/>, which makes
    /// loopback calls to the backend's `/remodel/*` routes, runs the two ModelCheck dumps in
    /// process, and puts the copy on screen through <see cref="SwRemodelSeat"/>. This method
    /// names those pieces; it decides nothing.
    ///
    /// <b>The remodel secret is read fresh per call</b>, off <see cref="ToolServiceGate"/>
    /// rather than captured: the tool service does not exist until the first document is open,
    /// and a pipeline holding the value it saw at add-in load would hold null forever.
    ///
    /// Started even when the tool service is not listening yet. The pane really has that state,
    /// and the refusal the engineer then reads - `BridgeUnavailable`, by name - is a better
    /// answer than a tab that never came up.
    /// </summary>
    private void StartRemodelHost(ReviewHostOptions reviewOptions)
    {
        IReviewDump? dump = reviewOptions.Dump;
        if (_pane == null || _swApp == null || _applicationThread == null || dump == null)
        {
            return;
        }

        // Named once: the page, the pipeline and the pipeline's HTTP client all ask the same
        // question, and three spellings of it would be three chances for one of them to go on
        // calling a port `settings.save` has already restarted the child off.
        Func<BackendEndpoint?> endpoint = () => _backend?.Endpoint;

        _remodelHost = new RemodelHost(new RemodelHostOptions(
            _pane.RemodelChannel,
            () => (_reviewHost?.Settings ?? UserSettings.Defaults()).RunRoot)
        {
            Backend = endpoint,
            CurrentDocument = CurrentDocument,
            Pipeline = new BackendRemodelPipeline(
                endpoint,
                () => _toolService?.RemodelBridge,
                CurrentDocument,
                dump,
                new SwRemodelSeat(_swApp, _applicationThread),
                new RemodelBackendClient(endpoint)),
            EntityResolver = () => reviewOptions.EntityResolver,

            // The same one answer the Model check tab registers through: `remodel.show_change`
            // resolves against the copy on screen, but the Ask tab's working folder and the
            // step strip both read the pane's latest run, and a remodel that registered
            // somewhere else would open the terminal in an unrelated folder.
            //
            // Registering it also points `RunPackageIndex` at this folder, which is how the
            // Review and Model check tabs resolve a `document_id` to a path. A remodel folder
            // holds its reading of the tree as `package-before.json`, so the index reads that
            // name too (`RunPackageIndex.PackageNames`); without it, pressing Remodel would
            // cost those tabs the full path on every Show.
            RegisterLatestRun = runDirectory =>
            {
                _reviewHost?.TrackCheck(runDirectory);
                _pane?.RefreshSteps();
            },

            // The configured key, and the remodel secret as well: this host relays the
            // backend's own sentences to the page, and a `/remodel/*` failure is exactly the
            // kind of message that could quote the credential it was called with (FR-015).
            Secrets = () => new[]
            {
                (_reviewHost?.Settings ?? UserSettings.Defaults()).ResolveApiKey().Key,
                _toolService?.RemodelBridge?.Secret,
            },
        });

        StartRemodelPump();
        _pane.RemodelPageMessageReceived += OnRemodelPageMessage;
    }

    private void OnRemodelPageMessage(object sender, string json)
    {
        try
        {
            _remodelMessages.Add(json);
        }
        catch (Exception)
        {
            // The pump is shutting down; the page is about to go with it.
        }
    }

    private void StartRemodelPump()
    {
        _remodelPump = new Thread(() =>
        {
            foreach (string json in _remodelMessages.GetConsumingEnumerable())
            {
                try
                {
                    _remodelHost?.Receive(json);
                }
                catch (Exception)
                {
                    // RemodelHost.Receive answers its own failures; an exception escaping onto
                    // this background thread would take SOLIDWORKS down with it.
                }
            }
        })
        {
            IsBackground = true,
            Name = "swreview-remodel-messages",
        };

        _remodelPump.Start();
    }

    private void StopRemodelPump()
    {
        if (_remodelPump == null)
        {
            return;
        }

        try
        {
            _remodelMessages.CompleteAdding();
        }
        catch (Exception)
        {
        }

        // Bounded, like the other two pumps. This one is the most likely to still be busy - a
        // run is bounded at twenty minutes - and SOLIDWORKS is still not made to wait for it:
        // the run's own artifacts are on disk and the change log is what the engineer reads.
        _remodelPump.Join(TimeSpan.FromSeconds(2));
        _remodelPump = null;
    }

    /// <summary>
    /// T048. The tool service's lifetime, as three delegates: when it may start, how, and what
    /// happens to the two secrets it mints.
    ///
    /// The review secret goes into <see cref="ReviewHostOptions.Bridge"/>, which is the
    /// `bridge` field of the next `POST /sessions` - so a review started before the first
    /// document simply has no bridge, and the Python side falls back to its own attach. The
    /// general-chat secret stays on the gate and is read by the terminal through
    /// <see cref="ToolService"/>; it never reaches the backend.
    ///
    /// Nothing here runs on the application thread: <see cref="ToolServiceHost.Start"/>
    /// marshals its attach onto that thread and waits, and <see cref="ToolServiceGate"/>
    /// schedules the start off whichever thread asked for it.
    /// </summary>
    private ToolServiceGate CreateToolServiceGate(ReviewHostOptions reviewOptions)
    {
        TaskPaneControl pane = _pane!;
        ISldWorks app = _swApp!;

        return new ToolServiceGate(
            () => CurrentDocument() != null,
            () => ToolServiceHost.Start(new ToolServiceOptions(app, new ControlAppThreadInvoker(pane))),
            service => reviewOptions.Bridge = service.ReviewBridge,
            Report);
    }

    private void StartBackend(UserSettings settings, ResolvedApiKey key)
    {
        try
        {
            // To both pages. The Model check tab calls `/checks/rms` itself with the endpoint
            // its `init` carried, so a tab opened while the backend was still starting holds a
            // null endpoint; the `ready` below is what tells it to ask again. A page nobody has
            // opened yet is not a problem: `PageChannel` asks for the view per post and drops
            // the message when there is none.
            PostStatusToPages("backend_starting", "Starting the review backend...");
            _backend?.Start(settings, key);
            PostStatusToPages("ready", "Backend ready.");
        }
        catch (Exception failure)
        {
            // Through the host's own PostStatus, which masks the key (FR-015). Not every
            // failure here is the BackendStartException whose message BackendProcess already
            // redacted - a job-object failure, a key-resolution failure, or anything thrown
            // before that wrapper - and the page must never be the first place a key appears.
            // Reported to the page and to the log, never thrown from a thread pool thread,
            // where it would end the process.
            PostStatusToPages("error", failure.Message);
            Report("The SwReview backend did not start.", failure);
        }
    }

    /// <summary>
    /// One backend lifecycle `status` to every page that has a backend of its own to track.
    ///
    /// To every page, but not every stage: the Remodel page's contract closes its `status`
    /// stages to the run's own phases plus `ready` and `error`, so that page's share is
    /// filtered through <see cref="RemodelHost.IsStatusStage"/>.
    ///
    /// Each host masks the configured key out of the message itself (FR-015), which is why this
    /// hands both of them the raw text rather than redacting once here: the masking belongs to
    /// the thing that posts to a page, and a caller that remembered to redact would be the one
    /// place it could be forgotten.
    /// </summary>
    private void PostStatusToPages(string stage, string message)
    {
        _reviewHost?.PostStatus(stage, message);
        _modelCheckHost?.PostStatus(stage, message);

        // The Remodel page's `status` stages are a closed list that names the three
        // backend-lifecycle stages posted here, so today every one of them goes through; the
        // gate is what keeps a stage another page grows later from being written into tab 5's
        // run line unannounced. `ready` is also what tells a Remodel tab opened during the
        // boot to ask for its `init` again.
        if (RemodelHost.IsStatusStage(stage))
        {
            _remodelHost?.PostStatus(stage, message);
        }
    }

    /// <summary>
    /// The document the pane is looking at, read on the application thread. Null when nothing is
    /// open, and null when what is open has never been saved - every id in the package is
    /// derived from the document path, so an unsaved document cannot be reviewed.
    /// </summary>
    private PageDocument? CurrentDocument()
    {
        ISldWorks? app = _swApp;
        IApplicationThread? thread = _applicationThread;
        if (app == null || thread == null)
        {
            return null;
        }

        try
        {
            return thread.Invoke<PageDocument?>(() =>
            {
                var document = app.ActiveDoc as IModelDoc2;
                string path = document == null ? string.Empty : document.GetPathName();
                if (document == null || string.IsNullOrEmpty(path))
                {
                    return null;
                }

                var configuration = document.ConfigurationManager == null
                    ? null
                    : document.ConfigurationManager.ActiveConfiguration as IConfiguration;
                return new PageDocument(path, configuration == null ? null : configuration.Name);
            });
        }
        catch (Exception)
        {
            // A pane whose handle is gone, or a SOLIDWORKS that will not answer: the page is
            // told there is no document, which is the refusal it would get from the host anyway.
            return null;
        }
    }

    /// <summary>
    /// SOLIDWORKS activated another document. Nothing here may throw: this is a COM event sink
    /// on the application thread, and an exception out of it is SOLIDWORKS' problem.
    /// </summary>
    private int OnActiveDocumentChanged()
    {
        try
        {
            _reviewHost?.DocumentChanged();
            _modelCheckHost?.DocumentChanged();

            // Tab 5 needs this for more than its header: a `document.changed` whose copy has
            // gone away aborts the run in flight, leaving the change log intact (RK-14).
            _remodelHost?.DocumentChanged();

            // Step 1 of the strip above the tabs has just changed answer, and this is the event
            // that says so (pane-host-messages.md, `document.changed`).
            _pane?.RefreshSteps();

            // The first document is what the tool service has been waiting for (T048). Once it
            // is running this is a no-op: one add-in instance, one tool service, one scope
            // (data-model.md).
            _toolService?.EnsureStarted();
        }
        catch (Exception failure)
        {
            Report("The pane could not be told the active document changed.", failure);
        }

        return 0;
    }

    private void OnPageMessage(object sender, string json)
    {
        try
        {
            _pageMessages.Add(json);
        }
        catch (Exception)
        {
            // The pump is shutting down; the page is about to go with it.
        }
    }

    private void StartPageMessagePump()
    {
        _pageMessagePump = new Thread(() =>
        {
            foreach (string json in _pageMessages.GetConsumingEnumerable())
            {
                try
                {
                    ReviewHost? host = _reviewHost;
                    if (host != null)
                    {
                        host.Receive(json);

                        // A `review.start` has just written a package into a new run folder,
                        // which is both of the step strip's answers at once. Every other
                        // message leaves them alone and costs one file-exists check.
                        _pane?.RefreshSteps();
                    }
                }
                catch (Exception)
                {
                    // ReviewHost.Receive answers its own failures; an exception escaping onto
                    // this background thread would take SOLIDWORKS down with it.
                }
            }
        })
        {
            IsBackground = true,
            Name = "swreview-page-messages",
        };

        _pageMessagePump.Start();
    }

    private void StopPageMessagePump()
    {
        if (_pageMessagePump == null)
        {
            return;
        }

        try
        {
            _pageMessages.CompleteAdding();
        }
        catch (Exception)
        {
        }

        // Bounded: the pump may be inside a dump, and SOLIDWORKS is not made to wait for it.
        _pageMessagePump.Join(TimeSpan.FromSeconds(2));
        _pageMessagePump = null;
    }

    /// <summary>
    /// Records a failure the engineer cannot otherwise see: in the pane when there is one, and
    /// in the add-in log either way. Never throws - it is called from the catch blocks that
    /// exist to keep SOLIDWORKS running.
    /// </summary>
    private void Report(string what, Exception failure)
    {
        // Both sinks below are masked (FR-015). `Exception.ToString()` carries every inner
        // exception's message, and the inner exception is where the unredacted launcher failure
        // sits: BackendProcess masks only the outer BackendStartException. A key must never be
        // written to a log file or shown in the panel.
        string summary = Redact(failure.Message);
        string detail = Redact(failure.ToString());

        try
        {
            ActionsPanel? panel = _panel;
            if (panel != null)
            {
                panel.ShowProgress(what + " " + summary);
            }
        }
        catch (Exception)
        {
        }

        Log(what + " " + detail);
    }

    /// <summary>
    /// Appends one timestamped line to <c>%LOCALAPPDATA%\SwReview\logs\addin.log</c> - the
    /// only log this add-in writes, and where <see cref="Report"/> puts its failures.
    ///
    /// The load checkpoints in <see cref="ConnectToSW"/> and the type initializer go through
    /// here too, rather than to a file of their own. A load failure is otherwise silent:
    /// SOLIDWORKS clears the startup flag and the add-in simply is not there, so the reverting
    /// check box is the whole error message. Four lines a session turn "it did not load" into
    /// a named step.
    ///
    /// Static, so the first line can be written before there is an instance, and it never
    /// throws: every caller is either a catch block that exists to keep SOLIDWORKS running or
    /// the type initializer, where an exception would itself become the load failure.
    ///
    /// The file handling lives in <see cref="AddInLog"/>, which <see cref="AssemblyRedirect"/>
    /// also writes through, so there is one mechanism and one file; it is a type of its own so
    /// that a test can redirect the folder without first running this class's type
    /// initializer, whose checkpoint is one of the lines being redirected.
    /// </summary>
    private static void Log(string line) => AddInLog.Write(line);

    /// <summary>
    /// Masks the configured key, through the host that knows what it is.
    ///
    /// Before the host exists - a failure during add-in load, before settings are read - there
    /// is no key to mask and nothing has yet touched one; the text is returned as it stands
    /// rather than dropped, because a load failure with no message is a failure nobody can act
    /// on (constitution Principle I).
    /// </summary>
    private string Redact(string text)
    {
        try
        {
            return _reviewHost?.Redact(text) ?? text;
        }
        catch (Exception)
        {
            return text;
        }
    }

    /// <summary>
    /// Runs the dump on the active document. The panel is told what is happening before and
    /// after; a failure shows the exception rather than leaving a half-written package with
    /// no explanation (constitution Principle I).
    /// </summary>
    private void OnDumpRequested(object sender, string outputDirectory)
    {
        if (_swApp == null || _panel == null)
        {
            return;
        }

        _panel.SetBusy(true);
        try
        {
            _panel.ShowProgress("Attaching to the active document...");

            SwSession session = SwSession.Attach(_swApp, documentPath: null, configurationName: null);

            _panel.ShowProgress(
                $"Dumping {System.IO.Path.GetFileName(session.DocumentPath)} "
                + $"[{session.Configuration.Name}]...");

            var options = new DumpOptions
            {
                OutputDirectory = outputDirectory,
                Configuration = session.Configuration.Name,
                Meshes = MeshFormat.Glb,
                Faces = FaceScope.Needed,
            };

            DumpResult result = SwDump.CreateWriter(_swApp, session).Write(options);

            _panel.ShowResult(
                $"Wrote {result.Package.Components.Count} components, "
                + $"{result.Package.Holes.Count} holes, "
                + $"{result.Package.Fasteners.Count} fasteners and "
                + $"{result.Gaps.Count} gaps to{System.Environment.NewLine}{result.PackageFilePath}");
        }
        catch (Exception error)
        {
            _panel.ShowError("The dump did not finish.", error);
        }
        finally
        {
            _panel.SetBusy(false);

            // Step 2 of the strip, whichever way the dump ended: a partial package is still a
            // package, and a failure that left none must not leave the strip saying there is one.
            _pane?.RefreshSteps();
        }
    }

    /// <summary>
    /// T076. Runs interference detection on the active document with the dialog's default
    /// settings and merges the results into the package.json already in the chosen folder.
    ///
    /// The settings are the defaults on purpose: the Task Pane is for the engineer standing
    /// at the model, and a row of checkboxes here would be a second, quieter place for the
    /// run configuration to differ from the console's. Anyone who needs other settings runs
    /// <c>swreview-extract interference</c>, which echoes them into the IR.
    /// </summary>
    private void OnInterferenceRequested(object sender, string outputDirectory)
    {
        if (_swApp == null || _panel == null)
        {
            return;
        }

        _panel.SetBusy(true);
        try
        {
            _panel.ShowProgress("Attaching to the active document...");
            SwSession session = SwSession.Attach(_swApp, documentPath: null, configurationName: null);

            EvidencePackage package = PackageAppender.Load(outputDirectory);

            _panel.ShowProgress("Walking the component tree...");
            SwScope scope = SwScope.Open(_swApp, session);

            _panel.ShowProgress($"Detecting interferences in {scope.Components.Count} components...");
            InterferenceRunResult result = new InterferenceRunner(scope.InterferenceSource()).Run(
                session.Configuration.Name,
                new[] { InterferencePair.WholeAssembly() },
                new InterferenceRunSettings(),
                handle => scope.Components.IdOf(handle),
                id => scope.Components.PatternOf(id));

            PackageAppender.Merge(
                package, session.Configuration.Name, result.Interferences, result.Gaps);
            string path = PackageAppender.Save(outputDirectory, package);

            _panel.ShowResult(
                $"{result.Interferences.Count} interference rows and {result.Gaps.Count} gaps "
                + $"appended to{System.Environment.NewLine}{path}");
        }
        catch (Exception error)
        {
            _panel.ShowError("Interference detection did not finish.", error);
        }
        finally
        {
            _panel.SetBusy(false);
        }
    }

    /// <summary>
    /// T076. Captures whatever is selected in SOLIDWORKS right now.
    ///
    /// The selection is the input, so the engineer picks the face or component in the
    /// graphics area and presses the button. Its persistent reference is taken first and
    /// the capture is driven from that reference, which is the same path the console and the
    /// bridge take - so a capture made here is navigable from the report exactly like one
    /// made from a review (Principle IV).
    /// </summary>
    private void OnCaptureRequested(object sender, CaptureRequest request)
    {
        if (_swApp == null || _panel == null)
        {
            return;
        }

        _panel.SetBusy(true);
        try
        {
            _panel.ShowProgress("Attaching to the active document...");
            SwSession session = SwSession.Attach(_swApp, documentPath: null, configurationName: null);

            object? selected = SelectedEntity(session);
            if (selected == null)
            {
                _panel.ShowResult("Select a face, edge or component in the graphics area first.");
                return;
            }

            EvidencePackage package = PackageAppender.Load(request.OutputDirectory);
            SwScope scope = SwScope.Open(_swApp, session);

            ScopedPersistRef reference = scope.Refs.Get(session.Document, selected);

            _panel.ShowProgress($"Capturing the selection ({request.View})...");
            var captures = new CaptureService(
                scope.CaptureView(), PackageAppender.CaptureIds(package));
            CaptureResult result = captures.Capture(
                reference.Base64, null, request.View, request.OutputDirectory, "Task Pane capture");

            PackageAppender.Merge(package, result.Capture, result.Gap);
            string path = PackageAppender.Save(request.OutputDirectory, package);

            if (!result.Succeeded)
            {
                _panel.ShowResult(
                    $"No image: {result.Gap!.Reason}."
                    + $"{System.Environment.NewLine}The gap was appended to {path}.");
                return;
            }

            _panel.ShowResult(
                $"Wrote {result.Capture!.File}"
                + $"{System.Environment.NewLine}and appended {result.Capture.Id} to {path}");
        }
        catch (Exception error)
        {
            _panel.ShowError("The capture did not finish.", error);
        }
        finally
        {
            _panel.SetBusy(false);
        }
    }

    /// <summary>The first selected object, or null when nothing is selected.</summary>
    private static object? SelectedEntity(ISwSession session)
    {
        var selection = session.Gate.Call(
            "SelectionManager", () => session.Document.SelectionManager) as ISelectionMgr;

        if (selection == null)
        {
            return null;
        }

        int count = session.Gate.Call(
            "GetSelectedObjectCount2", () => selection.GetSelectedObjectCount2(-1));

        if (count < 1)
        {
            return null;
        }

        // 1-based, and -1 means "in any configuration".
        return session.Gate.Call("GetSelectedObject6", () => selection.GetSelectedObject6(1, -1));
    }

    /// <summary>
    /// Written by regasm /codebase. SOLIDWORKS reads these keys at startup to find the
    /// add-in; without them the COM class is registered but never loaded.
    /// </summary>
    [ComRegisterFunction]
    public static void RegisterFunction(Type type)
    {
        using (RegistryKey key = Registry.LocalMachine.CreateSubKey(AddInKeyPath))
        {
            key.SetValue(null, 1, RegistryValueKind.DWord);       // load at startup
            key.SetValue("Description", AddInDescription, RegistryValueKind.String);
            key.SetValue("Title", AddInTitle, RegistryValueKind.String);
        }

        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(StartupKeyPath))
        {
            key.SetValue(null, 1, RegistryValueKind.DWord);       // enabled for this user
        }
    }

    /// <summary>Written by regasm /unregister. Leaves nothing behind.</summary>
    [ComUnregisterFunction]
    public static void UnregisterFunction(Type type)
    {
        Registry.LocalMachine.DeleteSubKeyTree(AddInKeyPath, throwOnMissingSubKey: false);
        Registry.CurrentUser.DeleteSubKeyTree(StartupKeyPath, throwOnMissingSubKey: false);
    }

    private static string AddInKeyPath => @"SOFTWARE\SOLIDWORKS\AddIns\{" + AddInGuid + "}";

    private static string StartupKeyPath => @"SOFTWARE\SOLIDWORKS\AddInsStartup\{" + AddInGuid + "}";
}

/// <summary>
/// The real <see cref="IApplicationThread"/>: hops onto the Task Pane control, which lives on
/// the SOLIDWORKS application STA thread, where every interop call has to happen
/// (constitution, Technical Constraints).
/// </summary>
internal sealed class PaneApplicationThread : IApplicationThread
{
    private readonly Control _control;

    public PaneApplicationThread(Control control)
    {
        _control = control ?? throw new ArgumentNullException(nameof(control));
    }

    public T Invoke<T>(Func<T> work)
    {
        if (work == null)
        {
            throw new ArgumentNullException(nameof(work));
        }

        if (_control.IsDisposed || !_control.IsHandleCreated)
        {
            // Invoking on a control with no handle throws from deep inside WinForms; this says
            // which control and why, where the caller can act on it.
            throw new InvalidOperationException(
                "the SwReview Task Pane is closed, so SOLIDWORKS cannot be called.");
        }

        if (!_control.InvokeRequired)
        {
            return work();
        }

        return (T)_control.Invoke(new Func<object>(() => work()!))!;
    }
}
