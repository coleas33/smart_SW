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
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using SwReview.AddIn.Terminal;
using SwReview.AddIn.ToolService;

namespace SwReview.AddIn;

/// <summary>
/// In-process SOLIDWORKS 2024 add-in host (research R1: in-process traversal is 10 to 100x
/// faster than out-of-process COM, and several many-parameter API members fail late-bound).
///
/// It owns the ISldWorks pointer and the Task Pane: the Review tab (the chat page in
/// WebView2, driven by <see cref="ReviewHost"/> over the loopback backend), the Terminal tab,
/// and the Actions tab's three buttons, all acting on the active document: <b>Dump IR</b> runs
/// <see cref="PackageWriter"/>, <b>Interference</b> runs <see cref="InterferenceRunner"/> and
/// <b>Capture selection</b> runs <see cref="CaptureService"/>. The latter two append to the
/// package.json that Dump IR wrote in the same folder, so their results can name its
/// components.
///
/// Everything the pane adds is behind a guard. SOLIDWORKS loads this add-in in-process, so an
/// exception out of <see cref="ConnectToSW"/> is the session's problem rather than ours: a
/// WebView2 runtime that is not installed leaves the Review tab showing the fallback panel and
/// the Actions tab working, and a backend that will not start is reported in the pane instead
/// of at load.
///
/// Registration (research R12, "Add-in hosting"). Both steps need an elevated x64 prompt;
/// the registry keys are written by the [ComRegisterFunction] below, so step 1 does both:
///
///   1. "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\regasm.exe" /codebase SwReview.AddIn.dll
///   2. Enable it for the current user (SOLIDWORKS writes this itself the first time the
///      add-in is ticked in Tools > Add-ins):
///        HKCU\SOFTWARE\SOLIDWORKS\AddInsStartup\{5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55} = 1
///
/// Build x64 and reference the interops from the seat install
/// (C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist) with Embed Interop Types
/// false; the NuGet SolidWorks.Interop packages are community published and are not used.
/// </summary>
[ComVisible(true)]
[Guid(AddInGuid)]
[ClassInterface(ClassInterfaceType.None)]
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
    /// Called by SOLIDWORKS when the add-in loads. Everything the extractor does runs on
    /// this thread, which is the application STA thread (constitution: all COM calls on one
    /// STA thread).
    /// </summary>
    public bool ConnectToSW(object ThisSW, int Cookie)
    {
        _swApp = (ISldWorks)ThisSW;
        _addInCookie = Cookie;

        // Required before any callback can be routed back to this add-in.
        _swApp.SetAddinCallbackInfo2(0, this, _addInCookie);

        // Two guards rather than one: a pane that cannot be created must not stop the add-in
        // loading, and a review host that cannot be started must not take the pane's Actions
        // tab with it. Neither failure may leave ConnectToSW.
        try
        {
            CreateTaskPane();
        }
        catch (Exception failure)
        {
            Report("The SwReview Task Pane could not be created.", failure);
        }

        try
        {
            StartReviewHost();
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
        }

        if (_events != null)
        {
            _events.ActiveDocChangeNotify -= OnActiveDocumentChanged;
            _events = null;
        }

        StopPageMessagePump();

        // Before the review host, because the tool service is what still holds SOLIDWORKS
        // pointers: the pipe stops listening and the scope is let go while the add-in is still
        // attached. Requests already in flight get the documented `error` (T047).
        _toolService?.Dispose();
        _toolService = null;

        // Before the review host and after the tool service: the terminal's CLI holds a
        // console and the generated profile, and it is stopped rather than left to the job.
        _terminalHost?.Dispose();
        _terminalHost = null;

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
            // The Terminal tab's run-folder rule (pane-host-messages.md): a terminal started
            // after a review belongs in that review's folder, so the CLI's generated profile,
            // its working directory and the evidence it is being asked about are one place.
            CurrentSessionRunDirectory = () => _reviewHost?.LatestSession?.RunDirectory,
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
            _pane, _toolService, () => _reviewHost?.Settings ?? UserSettings.Defaults(), _job);

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
            _reviewHost?.PostStatus("backend_starting", "Starting the review backend...");
            _backend?.Start(settings, key);
            _reviewHost?.PostStatus("ready", "Backend ready.");
        }
        catch (Exception failure)
        {
            // Through the host's own PostStatus, which masks the key (FR-015). Not every
            // failure here is the BackendStartException whose message BackendProcess already
            // redacted - a job-object failure, a key-resolution failure, or anything thrown
            // before that wrapper - and the page must never be the first place a key appears.
            // Reported to the page and to the log, never thrown from a thread pool thread,
            // where it would end the process.
            _reviewHost?.PostStatus("error", failure.Message);
            Report("The SwReview backend did not start.", failure);
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

        try
        {
            string folder = ReviewHostOptions.DefaultLogFolder();
            Directory.CreateDirectory(folder);
            File.AppendAllText(
                Path.Combine(folder, "addin.log"),
                string.Format(
                    "[{0:O}] {1} {2}{3}", DateTimeOffset.Now, what, detail, System.Environment.NewLine));
        }
        catch (Exception)
        {
            // There is nowhere left to report to.
        }
    }

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
