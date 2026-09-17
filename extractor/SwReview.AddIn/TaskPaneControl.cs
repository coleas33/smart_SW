using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;

namespace SwReview.AddIn;

/// <summary>
/// Creates the one <see cref="CoreWebView2Environment"/> the add-in uses.
///
/// Injected into <see cref="TaskPaneControl"/> so the runtime-missing path can be tested
/// (T042b): a workstation with no Evergreen runtime is the one failure the pane must survive,
/// and it cannot be produced by uninstalling WebView2 on the machine running the tests.
/// </summary>
public interface IWebViewEnvironmentFactory
{
    /// <summary>
    /// Creates the environment. Throws <see cref="WebView2RuntimeNotFoundException"/> when the
    /// Evergreen runtime is not installed.
    /// </summary>
    Task<CoreWebView2Environment> CreateAsync();
}

/// <summary>
/// The real factory: one environment over an explicit user data folder under
/// <c>%LOCALAPPDATA%</c>.
///
/// The folder is explicit because the default is derived from the host executable - here
/// <c>SLDWORKS.exe</c>, whose directory under <c>C:\Program Files\...</c> is not writable, and
/// whose default folder is shared with SOLIDWORKS' own WebView2 usage and with every other
/// add-in in the process (contracts/pane-host-messages.md). A second environment created over a
/// user data folder that is already open with different options fails at runtime, so the pane
/// creates exactly one and both tabs share it.
///
/// The folder is named for the add-in rather than for the process: WebView2 supports several
/// instances of the same application over one user data folder, and the options here never
/// vary, so a per-process folder would only leave a directory behind for every SOLIDWORKS
/// session the engineer ever ran.
/// </summary>
public sealed class WebViewEnvironmentFactory : IWebViewEnvironmentFactory
{
    /// <summary>`%LOCALAPPDATA%\SwReview\WebView2\{add-in guid}`.</summary>
    public static string UserDataFolder { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "SwReview",
        "WebView2",
        "{" + SwReviewAddIn.AddInGuid + "}");

    public Task<CoreWebView2Environment> CreateAsync()
    {
        // Created here rather than left to WebView2 so a permissions problem surfaces as a
        // directory failure with the path in it, not as a generic environment failure.
        Directory.CreateDirectory(UserDataFolder);
        return CoreWebView2Environment.CreateAsync(null, UserDataFolder, null);
    }
}

/// <summary>What <see cref="TaskPaneControl"/> needs from the add-in to build itself.</summary>
public sealed class TaskPaneOptions
{
    public TaskPaneOptions(IWebViewEnvironmentFactory environmentFactory, string runRoot)
    {
        EnvironmentFactory = environmentFactory ?? throw new ArgumentNullException(nameof(environmentFactory));
        RunRoot = runRoot ?? throw new ArgumentNullException(nameof(runRoot));
    }

    public IWebViewEnvironmentFactory EnvironmentFactory { get; }

    /// <summary>
    /// Where run folders are written. Shown in the fallback panel, because an engineer whose
    /// pane cannot start still needs to know where the last run's evidence went.
    /// </summary>
    public string RunRoot { get; }

    /// <summary>
    /// The folder the pages are served from as `https://swreview.invalid`. Defaults to `web`
    /// beside the add-in, which is where SwReview.AddIn.csproj copies every page.
    ///
    /// Served by <see cref="PageFileServer"/> through `WebResourceRequested` rather than by a
    /// virtual host mapping, so this is also the boundary a page request may not escape.
    /// </summary>
    public string WebFolder { get; set; } = DefaultWebFolder();

    /// <summary>
    /// The run folder of the chat session the pane is showing, or null when there is none.
    ///
    /// The Ask tab asks before it creates one of its own (contracts/pane-host-messages.md):
    /// a terminal started after a review belongs in that review's folder, so the CLI's generated
    /// profile, its working directory and the evidence it is being asked about are one place.
    /// It is a callback rather than a value because the answer changes every time a review
    /// starts, and the pane is built once.
    /// </summary>
    public Func<string?> CurrentSessionRunDirectory { get; set; } = () => null;

    /// <summary>The clock the terminal run folder is named from. Injected for the tests, like
    /// <c>ReviewHostOptions.Now</c>.</summary>
    public Func<DateTime> Now { get; set; } = () => DateTime.Now;

    /// <summary>
    /// Whether a document is open in SOLIDWORKS - step 1 of <see cref="StepStrip"/>.
    ///
    /// A callback rather than a value for the same reason
    /// <see cref="CurrentSessionRunDirectory"/> is one: the pane is built once and the answer
    /// changes every time the engineer opens or closes a model. The add-in feeds it from the
    /// same <c>CurrentDocument</c> the Review tab is refused by, so the strip and the Review
    /// button can never disagree about whether there is anything to review.
    /// </summary>
    public Func<bool> DocumentPresent { get; set; } = () => false;

    /// <summary>
    /// Whether the current session's run folder already holds an evidence package - step 2.
    ///
    /// The add-in answers it with <see cref="RunFolders.HasEvidence"/> over
    /// <see cref="TaskPaneControl.SessionRunDirectory"/>, which is the same folder the Terminal
    /// tab starts a CLI in and the same one the Extract tab is opened on.
    /// </summary>
    public Func<bool> EvidencePresent { get; set; } = () => false;

    /// <summary>
    /// Where the review backend is listening, or null before it has handshaken.
    ///
    /// The pane needs it because the pages no longer call loopback themselves: they call their
    /// own origin under <see cref="BackendProxy.PathPrefix"/> and this control serves those
    /// calls from C# (`docs/pane-backend-proxy.md`). A callback for the same reason
    /// <see cref="CurrentSessionRunDirectory"/> is one - the pane is built before the backend
    /// is started, and a `settings.save` starts a new child on a new port.
    /// </summary>
    public Func<BackendEndpoint?> Backend { get; set; } = () => null;

    /// <summary>
    /// How a proxied call is actually made. The real one is
    /// <see cref="BackendProxyHandler.Send"/>; injected so the wiring can be exercised against
    /// a fake with no backend, no Python and no socket.
    /// </summary>
    public Func<ProxiedRequest, ProxiedResponse> ProxySend { get; set; } = BackendProxyHandler.Send;

    private static string DefaultWebFolder() =>
        Path.Combine(Path.GetDirectoryName(typeof(TaskPaneOptions).Assembly.Location) ?? ".", "web");
}

/// <summary>
/// The Task Pane: <b>Review</b> (the chat page in WebView2), <b>Ask</b> (the CLI terminal,
/// US3), <b>Extract</b> (the three buttons that write an evidence package by hand),
/// <b>Model check</b> (the rule grade, tab 4, with no provider and no key) and
/// <b>Remodel</b> (tab 5: reorganize a copy of the open part, feature 004).
///
/// The tabs are named for what the engineer gets, not for what the code does, and each one
/// carries the same sentence twice - as a banner across the top of the tab and as the tab's
/// tooltip - because a pane whose tabs are nouns tells a first-time user nothing about
/// which of them to press. Above all four is the <see cref="StepStrip"/>: open a document,
/// extract evidence, review or ask, each done or pending with the reason. None of this is
/// decoration; every one of these sentences replaces a question the pane was being asked.
///
/// Five rules live here because nowhere else can enforce them:
///
/// <b>One environment for the process.</b> <see cref="EnvironmentAsync"/> creates it once and
/// hands the same task to every caller, so all four WebView2 tabs share one browser
/// process over one user data folder. Two environments over the same folder with different
/// options fail at runtime (contracts/pane-host-messages.md).
///
/// <b>The fourth and fifth tabs are loaded when they are opened.</b>
/// <see cref="ActivateModelCheckAsync"/> and <see cref="ActivateRemodelAsync"/> run on the
/// first selection of their tab rather than at add-in load, and a failure ends as the same
/// fallback panel the eager tabs get (T083, T121). Five tabs loaded up front would cost four
/// renderer processes inside the SOLIDWORKS process before anything was pressed (RK-11).
///
/// <b>Nothing thrown here reaches SOLIDWORKS.</b> <see cref="InitializeAsync"/> never throws.
/// The add-in is loaded in-process and an exception out of a Task Pane control on the
/// application thread is SOLIDWORKS' problem, not ours; a missing runtime ends as a panel that
/// says what to install and where the run folder is, with the Extract tab still working.
///
/// <b>The page stays on its own origin.</b> `NavigationStarting` and `NewWindowRequested`
/// cancel anything that is not `https://swreview.invalid/`, so a link in text a model wrote
/// cannot navigate the pane or open a browser window out of it.
///
/// <b>Every post to the page is marshalled here.</b> `PostWebMessageAsJson` has UI-thread
/// affinity and <see cref="ReviewHost"/> runs off the UI thread, so <see cref="ReviewChannel"/>
/// hops back onto this control (see <see cref="IPageChannel"/>).
/// </summary>
public sealed class TaskPaneControl : UserControl
{
    /// <summary>
    /// The fixed virtual host name every page is served from (pane-host-messages.md).
    ///
    /// A <i>name</i>, not a mapping: nothing calls `SetVirtualHostNameToFolderMapping` any
    /// more, because WebView2 raises no `WebResourceRequested` for a folder-mapped host and
    /// that event is how the pane serves both its pages and the backend proxy
    /// (docs/pane-backend-proxy.md).
    /// </summary>
    public const string VirtualHostName = "swreview.invalid";

    /// <summary>The page origin, and the origin the backend is started with.</summary>
    public const string PageOrigin = "https://swreview.invalid";

    /// <summary>
    /// The one `WebResourceRequested` filter every page gets: the whole origin, because the
    /// host now serves the page files as well as the backend prefix.
    /// </summary>
    public const string PageResourceFilter = PageOrigin + "/*";

    /// <summary>The Review page inside the web folder.</summary>
    public const string ReviewPageUrl = PageOrigin + "/Review/ReviewPage/index.html";

    /// <summary>The Ask tab's terminal page inside the same web folder (T060).</summary>
    public const string TerminalPageUrl = PageOrigin + "/Terminal/TerminalPage/index.html";

    /// <summary>The Model check tab's page, tab 4 (T083, contracts/model-check.md).</summary>
    public const string ModelCheckPageUrl = PageOrigin + "/Model/ModelCheckPage/index.html";

    /// <summary>The Remodel tab's page, tab 5 (T121, contracts/pane-remodel-messages.md).</summary>
    public const string RemodelPageUrl = PageOrigin + "/Remodel/RemodelPage/index.html";

    /// <summary>Where the Evergreen runtime comes from, shown when it is missing.</summary>
    public const string RuntimeDownloadUrl = "https://developer.microsoft.com/en-us/microsoft-edge/webview2/";

    /// <summary>What the <b>Review</b> tab is for, as its banner and as its tooltip.</summary>
    public const string ReviewPurpose =
        "Automated design review of the open assembly: press Review to extract evidence, run "
        + "the reviewer, and discuss its findings. Provider, model, and API key live under "
        + "Settings.";

    /// <summary>What the <b>Ask</b> tab is for. The read-only promise is the point of it.</summary>
    public const string AskPurpose =
        "Ask Codex anything about the open model. Read-only: it can query the extracted "
        + "evidence, measure, and capture, but cannot change or save anything.";

    /// <summary>What the <b>Extract</b> tab is for, and why most engineers never need it.</summary>
    public const string ExtractPurpose =
        "Manual extraction for the command line: write package.json, the evidence package "
        + "describing the open document (components, mates, holes, fasteners, geometry), add "
        + "interference results, capture the current selection. The Review tab does this for "
        + "you automatically.";

    /// <summary>
    /// What the <b>Model check</b> tab is for. "No AI, no key" is the sentence engineers ask
    /// for first, because every other tab in this pane needs one.
    /// </summary>
    public const string ModelCheckPurpose =
        "Grade the open document against the Resilient Modeling Strategy rules in seconds. "
        + "No AI, no key; read-only.";

    /// <summary>
    /// What the Model check tab holds before anyone opens it.
    ///
    /// The tab's WebView2 is created on first activation rather than at add-in load: a third
    /// page loaded into every SOLIDWORKS session that never presses Model check is a renderer
    /// process and a page load nobody asked for, and the tab is the one of the four an engineer
    /// is least likely to want on the day they install the add-in.
    /// </summary>
    public const string ModelCheckPending = "The Model check page opens when you select this tab.";

    /// <summary>
    /// What the <b>Remodel</b> tab is for (tab 5, contracts/pane-remodel-messages.md).
    ///
    /// The last sentence is the one an engineer needs before pressing anything on this tab,
    /// and it is the literal truth of the design rather than a reassurance: the run works on a
    /// copy it made in the run folder, and the source is never opened for writing at all.
    /// </summary>
    public const string RemodelPurpose =
        "Copy the open part and reorganize the copy under the Resilient Modeling Strategy, "
        + "then review the change list, the grade, and the geometry comparison. The original "
        + "file is never touched.";

    /// <summary>
    /// What the Remodel tab holds before anyone opens it.
    ///
    /// Tab 5 is lazy for a harder reason than tab 4 is (RK-11): five tabs loaded at add-in load
    /// would cost <b>four</b> renderer processes inside the SOLIDWORKS process before the
    /// engineer has pressed anything. Two of the five are created on first activation, so a
    /// session that opens neither pays for neither.
    /// </summary>
    public const string RemodelPending = "The Remodel page opens when you select this tab.";

    private readonly TaskPaneOptions _options;
    private readonly TabControl _tabs;
    private readonly TabPage _reviewTab;
    private readonly TabPage _terminalTab;
    private readonly TabPage _actionsTab;
    private readonly TabPage _modelCheckTab;
    private readonly TabPage _remodelTab;
    private readonly ActionsPanel _actions;
    private readonly StepStrip _steps;

    /// <summary>
    /// One proxy handler for the control, shared by every page: it holds no per-page state, and
    /// four of them would be four copies of the same two callbacks.
    /// </summary>
    private readonly BackendProxyHandler _proxy;

    /// <summary>
    /// The other half of the same handler: the pane's own page files, served from
    /// <see cref="TaskPaneOptions.WebFolder"/> because there is no folder mapping any more.
    /// One per control for the same reason <see cref="_proxy"/> is.
    /// </summary>
    private readonly PageFileServer _files;

    private Task<CoreWebView2Environment>? _environment;
    private WebView2? _reviewView;
    private WebView2? _terminalView;
    private WebView2? _modelCheckView;
    private WebView2? _remodelView;
    private Task? _modelCheckActivation;
    private Task? _remodelActivation;
    private bool _initializing;

    /// <summary>The terminal-first run folder this pane created, once it has created one.</summary>
    private string? _terminalRunFolder;

    public TaskPaneControl(TaskPaneOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));

        // Through the options rather than from captured values: the backend is started after
        // the pane is built, and a `settings.save` replaces it with a child on another port.
        _proxy = new BackendProxyHandler(
            () => _options.Backend(), request => _options.ProxySend(request));
        _files = new PageFileServer(_options.WebFolder);

        _reviewTab = NewTab("Review", ReviewPurpose, Note("Starting the review page..."));
        _terminalTab = NewTab("Ask", AskPurpose, Note("Starting the Ask page..."));

        _actions = new ActionsPanel();
        _actionsTab = NewTab("Extract", ExtractPurpose, _actions);
        _actionsTab.Padding = new Padding(6);

        // Tabs 4 and 5, each holding a placeholder until it is selected
        // (contracts/model-check.md, contracts/pane-remodel-messages.md).
        _modelCheckTab = NewTab("Model check", ModelCheckPurpose, Note(ModelCheckPending));
        _remodelTab = NewTab("Remodel", RemodelPurpose, Note(RemodelPending));

        _tabs = new TabControl { Dock = DockStyle.Fill, ShowToolTips = true };
        _tabs.TabPages.Add(_reviewTab);
        _tabs.TabPages.Add(_terminalTab);
        _tabs.TabPages.Add(_actionsTab);
        _tabs.TabPages.Add(_modelCheckTab);
        _tabs.TabPages.Add(_remodelTab);

        _steps = new StepStrip { Dock = DockStyle.Top };

        // The strip's one action (T084). The strip says what the evidence is; the tab that
        // extracts the rest of it is this pane's business, so the pane answers.
        _steps.ExtractFullEvidenceRequested += (sender, args) => _tabs.SelectedTab = _actionsTab;

        MinimumSize = new Size(260, 320);

        // The tabs first and the strip second: WinForms docks the last-added control first, so
        // the strip added after the Fill takes its band off the top and the tabs get the rest.
        Controls.Add(_tabs);
        Controls.Add(_steps);

        // Switching tabs is the moment an engineer is looking at the strip, and it costs a
        // file-exists check; the add-in refreshes it from the events that actually change it.
        _tabs.SelectedIndexChanged += OnSelectedTabChanged;

        ReviewChannel = new PageChannel(this, () => _reviewView);
        TerminalChannel = new PageChannel(this, () => _terminalView);
        ModelCheckChannel = new PageChannel(this, () => _modelCheckView);
        RemodelChannel = new PageChannel(this, () => _remodelView);

        RefreshSteps();
    }

    /// <summary>The three buttons: Extract evidence, Interference, Capture selection.</summary>
    public ActionsPanel Actions => _actions;

    /// <summary>The always-visible "1, 2, 3" above the tabs.</summary>
    public StepStrip Steps => _steps;

    /// <summary>Posts host messages to the Review page, from any thread.</summary>
    public IPageChannel ReviewChannel { get; }

    /// <summary>
    /// Posts host messages to the Terminal page, from any thread. This is the channel
    /// <c>TerminalSession</c> is given: its read loop is a background thread and
    /// `PostWebMessageAsJson` has UI-thread affinity, so every `terminal.output` is marshalled
    /// here (contracts/pane-host-messages.md).
    /// </summary>
    public IPageChannel TerminalChannel { get; }

    /// <summary>
    /// Posts host messages to the Model check page, from any thread. Valid before the page
    /// exists: the channel asks for the view per post, so a message sent to a tab nobody has
    /// opened yet is dropped rather than thrown (see <see cref="IPageChannel"/>).
    /// </summary>
    public IPageChannel ModelCheckChannel { get; }

    /// <summary>
    /// Posts host messages to the Remodel page, from any thread. The fourth channel, and the
    /// one that carries the most traffic while a run is going: `status`,
    /// `remodel.progress` and one `remodel.change` per change, all raised off the UI thread by
    /// the executor and marshalled here.
    /// </summary>
    public IPageChannel RemodelChannel { get; }

    /// <summary>
    /// One `{type, id, payload}` document from the Review page, raised on the UI thread. The
    /// add-in hands it to <see cref="ReviewHost"/> off this thread and one at a time.
    /// </summary>
    public event EventHandler<string>? PageMessageReceived;

    /// <summary>
    /// One `{type, id, payload}` document from the Terminal page, raised on the UI thread. Kept
    /// apart from <see cref="PageMessageReceived"/> rather than tagged with a source, because the
    /// two pages have separate vocabularies and separate handlers: a `terminal.input` that
    /// reached the review host would be answered `error` and a keystroke would go missing.
    /// </summary>
    public event EventHandler<string>? TerminalPageMessageReceived;

    /// <summary>
    /// One `{type, id, payload}` document from the Model check page, raised on the UI thread.
    /// Kept apart from the other two for the same reason they are kept apart from each other:
    /// the three pages have three vocabularies, and a `check.start` answered by the review host
    /// would be answered `error` while the tab waited.
    /// </summary>
    public event EventHandler<string>? ModelCheckPageMessageReceived;

    /// <summary>
    /// One `{type, id, payload}` document from the Remodel page, raised on the UI thread. Kept
    /// apart from the other three for the reason they are kept apart from each other: four
    /// pages, four vocabularies, and a `remodel.start` answered by the review host would be
    /// answered `error` while the tab waited.
    /// </summary>
    public event EventHandler<string>? RemodelPageMessageReceived;

    /// <summary>Whether the Review page is loaded (false on a workstation with no runtime).</summary>
    public bool ReviewPageReady => _reviewView != null && _reviewView.CoreWebView2 != null;

    /// <summary>
    /// The Review page itself, for the tests that drive the real pane's page rather than an
    /// offscreen copy of it (`BackendProxyPageTests`). Internal: nothing in the
    /// add-in reaches into a page, and everything that talks to one goes through
    /// <see cref="ReviewChannel"/>.
    /// </summary>
    internal CoreWebView2? ReviewPage => _reviewView?.CoreWebView2;

    /// <summary>Whether the Terminal page is loaded.</summary>
    public bool TerminalPageReady => _terminalView != null && _terminalView.CoreWebView2 != null;

    /// <summary>Whether the Model check page is loaded; false until the tab is first opened.</summary>
    public bool ModelCheckPageReady => _modelCheckView != null && _modelCheckView.CoreWebView2 != null;

    /// <summary>Whether the Remodel page is loaded; false until the tab is first opened.</summary>
    public bool RemodelPageReady => _remodelView != null && _remodelView.CoreWebView2 != null;

    /// <summary>
    /// The process's one WebView2 environment. Created on the first call and shared by every
    /// caller after it - including the failed call, so a workstation with no runtime asks once.
    /// </summary>
    public Task<CoreWebView2Environment> EnvironmentAsync()
    {
        if (_environment == null)
        {
            try
            {
                _environment = _options.EnvironmentFactory.CreateAsync()
                    ?? Task.FromException<CoreWebView2Environment>(
                        new InvalidOperationException("the WebView2 environment factory returned nothing."));
            }
            catch (Exception failure)
            {
                // A factory that throws synchronously (the runtime is missing) is the same
                // answer as one that returns a faulted task, and must be cached the same way.
                _environment = Task.FromException<CoreWebView2Environment>(failure);
            }
        }

        return _environment;
    }

    /// <summary>
    /// Creates the environment and loads the Review page. Never throws: a failure becomes the
    /// fallback panel, and the Extract tab keeps working.
    /// </summary>
    public async Task InitializeAsync()
    {
        if (_initializing || IsDisposed)
        {
            return;
        }

        _initializing = true;
        try
        {
            CoreWebView2Environment environment = await EnvironmentAsync().ConfigureAwait(true);
            if (IsDisposed)
            {
                return;
            }

            _reviewView = await AttachPageAsync(
                environment, _reviewTab, ReviewPageUrl, OnReviewMessageReceived).ConfigureAwait(true);

            // The Terminal page after the Review page and in the same try: both share the one
            // environment, and a terminal that could not be loaded must end as the same fallback
            // panel rather than as an exception on the application thread.
            _terminalView = await AttachPageAsync(
                environment, _terminalTab, TerminalPageUrl, OnTerminalMessageReceived).ConfigureAwait(true);
        }
        catch (Exception failure)
        {
            ShowFallback(failure);
        }
    }

    /// <summary>
    /// Loads the Model check page, once, on the first activation of its tab.
    ///
    /// Not at add-in load: a third page in every SOLIDWORKS session is a renderer process and a
    /// page load nobody asked for, and this is the tab an engineer is least likely to open on
    /// the day they install the add-in. It is the same environment the other two share, so the
    /// "one per process" rule is untouched - and when that environment failed, this tab shows
    /// the documented fallback panel exactly as they do rather than an empty tab.
    ///
    /// Never throws: it runs on the SOLIDWORKS UI thread, from a tab click. The task is cached
    /// including its failure, because the environment's failure is cached too and a retry would
    /// only ask a question that has already been answered.
    /// </summary>
    public Task ActivateModelCheckAsync()
    {
        if (IsDisposed)
        {
            return Task.CompletedTask;
        }

        return _modelCheckActivation ??= LoadModelCheckAsync();
    }

    private async Task LoadModelCheckAsync()
    {
        try
        {
            CoreWebView2Environment environment = await EnvironmentAsync().ConfigureAwait(true);
            if (IsDisposed)
            {
                return;
            }

            _modelCheckView = await AttachPageAsync(
                environment, _modelCheckTab, ModelCheckPageUrl, OnModelCheckMessageReceived)
                .ConfigureAwait(true);
        }
        catch (Exception failure)
        {
            _modelCheckView = null;
            SetTabContent(_modelCheckTab, BuildFallback(failure));
        }
    }

    /// <summary>
    /// Loads the Remodel page, once, on the first activation of its tab (T121).
    ///
    /// The same rule as tab 4 and for a harder reason: five tabs loaded at add-in load would
    /// cost four renderer processes inside the SOLIDWORKS process before the engineer has
    /// pressed anything, and this is the tab most sessions never open at all. It shares the one
    /// environment, so the "one per process" rule is untouched, and when that environment
    /// failed this tab shows the documented fallback panel exactly as the others do.
    ///
    /// Never throws: it runs on the SOLIDWORKS UI thread, from a tab click. The task is cached
    /// including its failure, so activating the tab twice loads the page once.
    /// </summary>
    public Task ActivateRemodelAsync()
    {
        if (IsDisposed)
        {
            return Task.CompletedTask;
        }

        return _remodelActivation ??= LoadRemodelAsync();
    }

    private async Task LoadRemodelAsync()
    {
        try
        {
            CoreWebView2Environment environment = await EnvironmentAsync().ConfigureAwait(true);
            if (IsDisposed)
            {
                return;
            }

            _remodelView = await AttachPageAsync(
                environment, _remodelTab, RemodelPageUrl, OnRemodelMessageReceived)
                .ConfigureAwait(true);
        }
        catch (Exception failure)
        {
            _remodelView = null;
            SetTabContent(_remodelTab, BuildFallback(failure));
        }
    }

    /// <summary>
    /// Switching tabs is the moment an engineer is looking at the step strip, and it is also
    /// the moment the Model check page is wanted for the first time.
    /// </summary>
    private void OnSelectedTabChanged(object sender, EventArgs args)
    {
        RefreshSteps();

        if (ReferenceEquals(_tabs.SelectedTab, _modelCheckTab))
        {
            // Not awaited: the page load must not block the tab from being drawn, and
            // ActivateModelCheckAsync answers its own failures.
            _ = ActivateModelCheckAsync();
        }
        else if (ReferenceEquals(_tabs.SelectedTab, _remodelTab))
        {
            _ = ActivateRemodelAsync();
        }
    }

    /// <summary>
    /// Loads one page into one tab. Every tab goes through here so none can be given a weaker
    /// set of guards than the others: they share a browser process and a page origin, so a
    /// terminal that followed an off-origin link would be doing it on the Review page's origin.
    /// </summary>
    private async Task<WebView2> AttachPageAsync(
        CoreWebView2Environment environment,
        TabPage tab,
        string url,
        EventHandler<CoreWebView2WebMessageReceivedEventArgs> onMessage)
    {
        var view = new WebView2();
        SetTabContent(tab, view);

        await view.EnsureCoreWebView2Async(environment).ConfigureAwait(true);

        CoreWebView2 core = view.CoreWebView2;

        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.IsSwipeNavigationEnabled = false;

        // The whole origin, one filter, one handler (docs/pane-backend-proxy.md section 4).
        // There is deliberately no `SetVirtualHostNameToFolderMapping`: WebView2 raises no
        // `WebResourceRequested` at all for a folder-mapped host, so a page served that way
        // cannot call its own origin under `/__backend` - which is the entire same-origin
        // proxy. `BackendProxyHandler.TryServe` answers the backend prefix and
        // `PageFileServer` answers the page's own files, so the pane keeps one origin, the CSP
        // stays `connect-src 'self'`, and there is no CORS anywhere.
        core.AddWebResourceRequestedFilter(
            PageResourceFilter,
            CoreWebView2WebResourceContext.All,
            CoreWebView2WebResourceRequestSourceKinds.All);
        core.WebResourceRequested += (sender, args) => ServePageResource(environment, args);

        core.NavigationStarting += OnNavigationStarting;
        core.NewWindowRequested += OnNewWindowRequested;
        core.WebMessageReceived += onMessage;

        core.Navigate(url);
        return view;
    }

    /// <summary>
    /// Answers every request on `https://swreview.invalid`: a `/__backend/...` call by calling
    /// the loopback backend from C# (<see cref="BackendProxy"/>), and anything else by reading
    /// the file out of the web folder (<see cref="PageFileServer"/>).
    ///
    /// Two servers, one order: <see cref="BackendProxyHandler.TryServe"/> first, and its null -
    /// "not mine" - is what hands the request to the file server. Nothing falls through to
    /// WebView2 any more, because there is no folder mapping behind this: an unanswered request
    /// is a blank tab, so the file server always answers, with a 404 when it will not serve.
    ///
    /// The order of the rest is the whole of it. The request is read <b>before</b> the deferral
    /// goes async: `args.Request` and its `Content` stream belong to this thread and to this
    /// handler call, and reading them after the first `await` reads a stream that has already
    /// been closed. The work itself runs off the UI thread, because it is a synchronous HTTP
    /// round trip or a file read and this is the SOLIDWORKS application thread. The response is
    /// created and assigned back on the UI thread, where the deferral is completed.
    ///
    /// `async void` because that is what a `WebResourceRequested` handler taking a deferral has
    /// to be; nothing is allowed to escape it, so the body is a `try` around everything.
    /// </summary>
    private async void ServePageResource(
        CoreWebView2Environment environment, CoreWebView2WebResourceRequestedEventArgs args)
    {
        CoreWebView2Deferral deferral;
        string uri;
        string method;
        var headers = new List<KeyValuePair<string, string>>();
        byte[]? body;

        try
        {
            uri = args.Request.Uri;
            method = args.Request.Method;
            foreach (KeyValuePair<string, string> header in args.Request.Headers)
            {
                headers.Add(header);
            }

            body = ReadRequestContent(args.Request.Content);
            deferral = args.GetDeferral();
        }
        catch (Exception)
        {
            // The page went away mid-request. There is nothing to answer and nothing to log to.
            return;
        }

        try
        {
            ProxiedResponse answer = await Task.Run(
                () => _proxy.TryServe(
                        uri,
                        method,
                        headers,
                        body == null ? null : new MemoryStream(body))
                    ?? _files.Serve(uri)).ConfigureAwait(true);

            if (!IsDisposed)
            {
                args.Response = environment.CreateWebResourceResponse(
                    new MemoryStream(answer.Content),
                    answer.Status,
                    // WebView2 rejects an empty reason phrase, and a backend that sent none
                    // still sent a status.
                    string.IsNullOrEmpty(answer.Reason) ? "OK" : answer.Reason,
                    answer.Headers);
            }
        }
        catch (Exception)
        {
            // Left unanswered on purpose. WebView2 then tries the request itself and fails -
            // a network error for a backend call, which the page already renders, and a
            // missing resource for a page file, which is a tab that does not finish loading.
            // Both are worse than an answer and better than the alternative: an exception out
            // of an `async void` here would surface inside SOLIDWORKS, which is the one
            // outcome this pane never allows. Nothing reaches here that the two servers below
            // answer themselves - they return a response for every input, including a 404.
        }
        finally
        {
            try
            {
                deferral.Complete();
            }
            catch (Exception)
            {
                // The page or the WebView2 went away while the call was outstanding - up to
                // the proxy's own timeout, which a `settings.save` restart or a disposed pane
                // both make reachable. There is nothing left to answer, and this `finally`
                // sits outside the guard above, so an exception here would escape an
                // `async void` and surface inside SOLIDWORKS: the one outcome this pane
                // never allows.
            }
        }
    }

    /// <summary>
    /// The request body, read whole on the UI thread. Null when there is none, which is what
    /// <see cref="BackendProxyHandler"/> means by "no body" - a `GET` has no content stream at
    /// all.
    /// </summary>
    private static byte[]? ReadRequestContent(Stream? content)
    {
        if (content == null)
        {
            return null;
        }

        using (var buffer = new MemoryStream())
        {
            content.CopyTo(buffer);
            byte[] bytes = buffer.ToArray();
            return bytes.Length == 0 ? null : bytes;
        }
    }

    /// <summary>
    /// The folder this pane's session is working in, or null when there is none yet.
    ///
    /// Two sources, in order: the chat session the Review tab is showing, and - when there has
    /// been no review - the terminal-first folder this pane created for the Ask tab. One or the
    /// other is what `init.evidence` describes, what the Extract tab opens on, and what the
    /// step strip means by "this session".
    ///
    /// Nothing is created here. It is asked on every repaint of the strip, and a run folder per
    /// glance would fill the run root with empty timestamps.
    /// </summary>
    public string? SessionRunDirectory
    {
        get
        {
            string? session = _options.CurrentSessionRunDirectory();
            if (!string.IsNullOrWhiteSpace(session) && Directory.Exists(session))
            {
                return session;
            }

            // A folder that has gone missing underneath the pane - tidied up, or on a share
            // that went away - is not this session's folder any more.
            string? terminal = _terminalRunFolder;
            return !string.IsNullOrWhiteSpace(terminal) && Directory.Exists(terminal)
                ? terminal
                : null;
        }
    }

    /// <summary>
    /// Where the Ask tab runs (contracts/pane-host-messages.md): <see cref="SessionRunDirectory"/>
    /// when there is one, and otherwise a fresh
    /// `&lt;run_root&gt;/&lt;yyyyMMdd-HHmmss&gt;-terminal` created through the same
    /// <see cref="RunFolders"/> helper <see cref="ReviewHost"/> names its own folders with.
    ///
    /// The tab is reachable with no review and no document open, so the folder is created rather
    /// than assumed. The one it creates is remembered, because everything that follows - the
    /// CLI's working directory, the package `evidence.extract` writes, the MCP server's own
    /// run folder - has to be the same folder, and the next call must not make a second one.
    /// </summary>
    public string TerminalRunFolder()
    {
        string? session = SessionRunDirectory;
        if (session != null)
        {
            return session;
        }

        string created = RunFolders.CreateForTerminal(_options.RunRoot, _options.Now());
        _terminalRunFolder = created;
        return created;
    }

    /// <summary>
    /// Repaints the step strip and re-suggests the Extract tab's output folder, from any thread.
    ///
    /// Called by the add-in whenever one of the two answers can have changed - the active
    /// document, and the end of a dump - and by the pane itself when a tab is selected, which
    /// is the moment an engineer is looking at it. Never throws: both callbacks reach into
    /// SOLIDWORKS, and this runs on the application thread.
    /// </summary>
    public void RefreshSteps()
    {
        if (IsDisposed)
        {
            return;
        }

        try
        {
            if (IsHandleCreated && InvokeRequired)
            {
                BeginInvoke(new Action(RefreshOnUiThread));
                return;
            }

            RefreshOnUiThread();
        }
        catch (Exception)
        {
            // The pane closed between the check and the call. There is nobody left to tell.
        }
    }

    private void RefreshOnUiThread()
    {
        bool document = Ask(_options.DocumentPresent);
        bool evidence = Ask(_options.EvidencePresent);
        string? session = SessionRunDirectory;

        // The profile is read from the package itself rather than remembered from the dump
        // that wrote it: the folder the pane is showing may have been written by a previous
        // session, by the command line, or by the other pane in a second SOLIDWORKS window.
        bool checkOnly = evidence && RunFolders.ProfileOf(session) == DumpProfile.ModelCheck;

        _steps.Show(document, evidence, checkOnly);

        try
        {
            // Never the check folder: a full extract into it would overwrite the package its
            // own `session.json` and `report.md` describe (T084). The engineer chooses where
            // the full dump goes, which is what the Extract tab's folder box is for.
            _actions.SuggestOutputDirectory(checkOnly ? null : session);
        }
        catch (Exception)
        {
            // The suggestion is a convenience; the engineer can always choose a folder.
        }
    }

    /// <summary>One step callback, answered "no" when it cannot answer at all.</summary>
    private static bool Ask(Func<bool> question)
    {
        try
        {
            return question();
        }
        catch (Exception)
        {
            // A SOLIDWORKS that will not answer is the same as nothing being open: the strip
            // says the step is pending, which is the honest answer and the actionable one.
            return false;
        }
    }

    /// <summary>
    /// The page may not leave its own origin. A model's text can contain a link, and a pane
    /// that followed one would be showing a remote page inside SOLIDWORKS with the backend
    /// token in its renderer.
    /// </summary>
    private void OnNavigationStarting(object sender, CoreWebView2NavigationStartingEventArgs e)
    {
        if (!IsOwnPage(e.Uri))
        {
            e.Cancel = true;
        }
    }

    /// <summary>
    /// No new windows at all. There is no second window in a Task Pane, and a
    /// `window.open` that opened a browser would take the page's URL out of the pane's control.
    /// </summary>
    private void OnNewWindowRequested(object sender, CoreWebView2NewWindowRequestedEventArgs e)
    {
        e.Handled = true;
    }

    private void OnReviewMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e) =>
        Raise(e, PageMessageReceived);

    private void OnModelCheckMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e) =>
        Raise(e, ModelCheckPageMessageReceived);

    private void OnRemodelMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e) =>
        Raise(e, RemodelPageMessageReceived);

    private void OnTerminalMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e) =>
        Raise(e, TerminalPageMessageReceived);

    private void Raise(CoreWebView2WebMessageReceivedEventArgs e, EventHandler<string>? handler)
    {
        if (!IsOwnPage(e.Source))
        {
            return;
        }

        string json;
        try
        {
            json = e.WebMessageAsJson;
        }
        catch (Exception)
        {
            // The page posted something that is not JSON; there is nothing to dispatch.
            return;
        }

        handler?.Invoke(this, json);
    }

    /// <summary>`https://swreview.invalid/...`, or the blank page WebView2 starts on.</summary>
    private static bool IsOwnPage(string? uri) =>
        !string.IsNullOrEmpty(uri)
        && (uri!.StartsWith(PageOrigin + "/", StringComparison.OrdinalIgnoreCase)
            || string.Equals(uri, "about:blank", StringComparison.OrdinalIgnoreCase));

    // ---- the runtime-missing fallback ------------------------------------------------------

    /// <summary>
    /// What the engineer sees when WebView2 cannot be had: what to install, where to get it,
    /// where their runs are, and what actually failed - all as plain text they can read off the
    /// screen and copy, because the pane cannot render a link they could click.
    /// </summary>
    private void ShowFallback(Exception failure)
    {
        _reviewView = null;
        _terminalView = null;
        SetTabContent(_reviewTab, BuildFallback(failure));
        SetTabContent(_terminalTab, BuildFallback(failure));
    }

    /// <summary>
    /// One tab: its caption, the sentence that says what it is for, and what fills it.
    ///
    /// The sentence is held on the tab as its <see cref="TabPage.ToolTipText"/> and read back
    /// from there by <see cref="SetTabContent"/> for the banner, so the two can never drift:
    /// they are the same string in the same place, shown twice.
    /// </summary>
    private static TabPage NewTab(string caption, string purpose, Control content)
    {
        var tab = new TabPage(caption)
        {
            Padding = new Padding(0),
            UseVisualStyleBackColor = true,
            ToolTipText = purpose,
        };

        SetTabContent(tab, content);
        return tab;
    }

    /// <summary>
    /// Replaces what a tab is showing, keeping its purpose banner at the top.
    ///
    /// Every replacement goes through here - the page that loaded, the fallback panel that
    /// replaced it - because a tab that lost its banner would lose it exactly when the engineer
    /// most needs to know what the tab was for.
    /// </summary>
    private static void SetTabContent(TabPage page, Control content)
    {
        page.Controls.Clear();

        // The content first and the banner second: WinForms docks the last-added control
        // first, so the banner added after the Fill takes its band off the top.
        content.Dock = DockStyle.Fill;
        page.Controls.Add(content);
        page.Controls.Add(Banner(page.ToolTipText));
    }

    /// <summary>
    /// The purpose line across the top of a tab. `AutoSize` with `Dock = Top` is what makes it
    /// grow to however many lines the sentence needs at the width the pane has been dragged to;
    /// a fixed height would cut the sentence off on a narrow pane, which is the pane an
    /// engineer docks beside a model.
    /// </summary>
    private static Label Banner(string text) => new Label
    {
        Dock = DockStyle.Top,
        AutoSize = true,
        Padding = new Padding(6, 6, 6, 6),
        Text = text ?? string.Empty,
    };

    private Control BuildFallback(Exception failure)
    {
        var panel = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Padding = new Padding(8) };

        // DockStyle.Top stacks in reverse order of addition, so these are added bottom-first.
        panel.Controls.Add(Note("Details: " + failure.Message));
        panel.Controls.Add(Copyable(_options.RunRoot));
        panel.Controls.Add(Note("Reviews are written to:"));
        panel.Controls.Add(Copyable(RuntimeDownloadUrl));
        panel.Controls.Add(Note("Install the Evergreen runtime from:"));
        panel.Controls.Add(Note(
            "The Microsoft Edge WebView2 runtime is not available, so the Review, Ask and "
            + "Model check tabs cannot be shown. The Extract tab still works."));

        return panel;
    }

    private static Label Note(string text) => new Label
    {
        Dock = DockStyle.Top,
        AutoSize = false,
        Height = 56,
        Padding = new Padding(0, 4, 0, 4),
        Text = text,
    };

    /// <summary>A read-only box, so a path or a URL can be selected and copied.</summary>
    private static TextBox Copyable(string text) => new TextBox
    {
        Dock = DockStyle.Top,
        ReadOnly = true,
        BorderStyle = BorderStyle.FixedSingle,
        BackColor = SystemColors.Window,
        Text = text,
    };

    // ---- posting to the page -----------------------------------------------------------------

    /// <summary>
    /// The real <see cref="IPageChannel"/>: marshals onto the pane, then posts.
    ///
    /// The page is named by a callback rather than held, because the view a tab is showing is
    /// replaced when the pane reloads it and set to null when the runtime turns out to be
    /// missing; a channel that had captured the view would post into a disposed one.
    /// </summary>
    private sealed class PageChannel : IPageChannel
    {
        private readonly TaskPaneControl _pane;
        private readonly Func<WebView2?> _view;

        public PageChannel(TaskPaneControl pane, Func<WebView2?> view)
        {
            _pane = pane;
            _view = view;
        }

        public void PostMessage(string json) => _pane.PostToPage(_view, json);
    }

    private void PostToPage(Func<WebView2?> view, string json)
    {
        if (json == null || IsDisposed || !IsHandleCreated)
        {
            return;
        }

        try
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action<Func<WebView2?>, string>(PostOnUiThread), view, json);
                return;
            }

            PostOnUiThread(view, json);
        }
        catch (Exception)
        {
            // The pane closed between the check and the call. There is nobody left to tell.
        }
    }

    private void PostOnUiThread(Func<WebView2?> selector, string json)
    {
        WebView2? view = selector();
        if (view == null || view.IsDisposed || view.CoreWebView2 == null)
        {
            return;
        }

        try
        {
            view.CoreWebView2.PostWebMessageAsJson(json);
        }
        catch (Exception)
        {
            // The page navigated away or the browser process died; the host cannot help.
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            WebView2? review = _reviewView;
            WebView2? terminal = _terminalView;
            _reviewView = null;
            _terminalView = null;
            review?.Dispose();
            terminal?.Dispose();
        }

        base.Dispose(disposing);
    }
}

/// <summary>
/// The three steps, above the tabs and always visible: open a document, extract evidence,
/// then review or ask.
///
/// It exists because the pane had no order in it. Three tabs, all reachable, all of them
/// answering "there is no document" or "there is no package" in their own words and in their
/// own corner of the screen - so the engineer's question was never "what does this tab do" but
/// "why did nothing happen". A step that is pending says why it is pending, in the same words
/// everywhere, and a step that is done says so.
///
/// Under step 2, when this session's evidence came from a Model check, one more line:
/// <see cref="CheckOnlyEvidence"/> and an <see cref="ExtractFullEvidence"/> button (T084,
/// FR-022). It is not a fourth step - the evidence is there and step 2 is done - but a review
/// of a check package reads "no holes" and "no fasteners" as facts about the design, and the
/// engineer has to know that before pressing Review rather than out of the report afterwards.
///
/// It decides nothing. The three facts it renders are answered by the add-in and by the pane
/// through <see cref="TaskPaneOptions.DocumentPresent"/>,
/// <see cref="TaskPaneOptions.EvidencePresent"/> and <see cref="RunFolders.ProfileOf"/>, and
/// the button raises an event rather than starting anything, which is what makes the whole
/// strip testable with no SOLIDWORKS and no WebView2 at all.
/// </summary>
public sealed class StepStrip : UserControl
{
    /// <summary>Said of every step that is not blocked: the same word in all three rows.</summary>
    public const string Ready = "ready";

    /// <summary>Why step 1 - and everything after it - is pending.</summary>
    public const string NoDocument = "no document open";

    /// <summary>Why step 2 is pending. "This session" is the pane's current run folder.</summary>
    public const string NoEvidence = "no evidence for this session yet";

    /// <summary>
    /// What the strip says when this session's evidence came from a Model check (FR-022).
    ///
    /// Not a step and not a warning: the evidence is there, it is simply a fraction of the
    /// design. A review of it reports "no holes" and "no fasteners" as facts about the model,
    /// so the sentence names what is in the package rather than what is missing from it, and
    /// the button beside it is the way to get the rest.
    /// </summary>
    public const string CheckOnlyEvidence = "Evidence: model check only (features and equations)";

    /// <summary>The action beside <see cref="CheckOnlyEvidence"/>: it opens the Extract tab,
    /// which dumps every phase.</summary>
    public const string ExtractFullEvidence = "Extract full evidence";

    private static readonly Color DoneColor = Color.FromArgb(0, 100, 0);

    private readonly Label _document;
    private readonly Label _evidence;
    private readonly Label _work;
    private readonly FlowLayoutPanel _notice;
    private readonly Label _noticeText;
    private readonly Button _extractFull;

    public StepStrip()
    {
        _work = Row();
        _noticeText = Row();
        _extractFull = new Button
        {
            Text = ExtractFullEvidence,
            AutoSize = true,
            Margin = new Padding(8, 0, 0, 0),
        };
        _extractFull.Click += (sender, args) => ExtractFullEvidenceRequested?.Invoke(this, EventArgs.Empty);

        _notice = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            WrapContents = false,
            Margin = new Padding(0),
            Padding = new Padding(0, 2, 0, 2),
            Visible = false,
        };
        _noticeText.Dock = DockStyle.None;
        _noticeText.Anchor = AnchorStyles.Left;
        _notice.Controls.Add(_noticeText);
        _notice.Controls.Add(_extractFull);

        _evidence = Row();
        _document = Row();

        AutoSize = true;
        AutoSizeMode = AutoSizeMode.GrowAndShrink;
        Padding = new Padding(6, 4, 6, 4);

        // Added last-to-first: DockStyle.Top stacks in reverse order of addition. The notice
        // sits between step 2, which put the evidence there, and step 3, which is the press
        // of Review it is about.
        Controls.Add(_work);
        Controls.Add(_notice);
        Controls.Add(_evidence);
        Controls.Add(_document);

        Show(document: false, evidence: false, checkOnly: false);
    }

    /// <summary>Raised by the <see cref="ExtractFullEvidence"/> button. The pane answers it by
    /// opening the Extract tab; the strip itself starts nothing.</summary>
    public event EventHandler? ExtractFullEvidenceRequested;

    /// <summary>The three lines as they read on screen, top to bottom. The tests' whole view.</summary>
    public IReadOnlyList<string> Lines => new[] { _document.Text, _evidence.Text, _work.Text };

    /// <summary>
    /// The partial-evidence sentence when it is showing, and the empty string when it is not.
    ///
    /// Beside <see cref="Lines"/> rather than inside it, because it is not a step: the three
    /// steps read exactly the same on a Model check package as on a full one.
    /// </summary>
    public string Notice => _notice.Visible ? _noticeText.Text : string.Empty;

    /// <summary>
    /// Repaints the strip from the two facts it is given.
    ///
    /// Step 3 needs both of them. Evidence alone is not ready: `ReviewHost` refuses to start
    /// without a document, so an engineer who extracted and then closed the model would be told
    /// Review was ready and watch the button do nothing - which is the complaint this strip
    /// exists to answer, printed by the strip itself.
    ///
    /// Its reason is the first thing in the way, because an engineer reading "Review or Ask -
    /// pending" wants the blocker, not a pointer to another line of the strip.
    /// </summary>
    /// <param name="document">Whether a document is open.</param>
    /// <param name="evidence">Whether this session's run folder holds an evidence package.</param>
    /// <param name="checkOnly">Whether that package came from a Model check, and therefore
    /// carries features and equations and none of the geometry phases (FR-022). It says
    /// nothing about the three steps: partial evidence is evidence, and step 2 is done.</param>
    public void Show(bool document, bool evidence, bool checkOnly)
    {
        bool ready = document && evidence;

        Set(_document, "1 Open a document", document, document ? Ready : NoDocument);
        Set(_evidence, "2 Extract evidence", evidence, evidence ? Ready : NoEvidence);
        Set(_work, "3 Review or Ask", ready, ready ? Ready : (document ? NoEvidence : NoDocument));

        _noticeText.Text = CheckOnlyEvidence;
        _notice.Visible = checkOnly;
    }

    private static void Set(Label row, string step, bool done, string reason)
    {
        row.Text = step + " - " + (done ? "done" : "pending") + ": " + reason;
        row.ForeColor = done ? DoneColor : SystemColors.GrayText;
    }

    private static Label Row() => new Label
    {
        Dock = DockStyle.Top,
        AutoSize = true,
        Padding = new Padding(0, 1, 0, 1),
    };
}

/// <summary>
/// The Extract tab: a folder to write to, the three buttons contracts/cli.md names -
/// <b>Extract evidence</b>, <b>Interference</b> and <b>Capture selection</b> - and a status
/// line.
/// Deliberately plain WinForms with no designer file; the whole UI is seven controls, and a
/// .Designer.cs would be more code than the panel.
///
/// Everything runs on THIS thread, which is the SOLIDWORKS application STA thread. A worker
/// thread would be smoother but would have to marshal every COM call back here anyway
/// (constitution, Technical Constraints), so the buttons disable themselves and the status
/// line reports progress instead.
///
/// All three buttons write into the same folder, because interference and capture append to
/// the package.json that Extract evidence wrote there: the results have to sit next to the
/// components they name. The folder is suggested rather than demanded: the pane opens it on
/// the current session's run folder, which is where the Review and Ask tabs are already
/// working, and an engineer who types another one keeps it.
/// </summary>
public sealed class ActionsPanel : UserControl
{
    private readonly Button _dumpButton;
    private readonly Button _interferenceButton;
    private readonly Button _captureButton;
    private readonly ComboBox _viewBox;
    private readonly TextBox _outputBox;
    private readonly Label _status;
    private readonly ToolTip _tips = new ToolTip();

    /// <summary>The last folder this panel put in the box itself, so an edit is never undone.</summary>
    private string? _suggested;

    public ActionsPanel()
    {
        _outputBox = new TextBox
        {
            Dock = DockStyle.Top,
            Height = 24,
            Text = string.Empty,
        };

        var browse = new Button
        {
            Dock = DockStyle.Top,
            Height = 28,
            Text = "Choose output folder...",
        };
        browse.Click += OnBrowse;

        _dumpButton = new Button
        {
            Dock = DockStyle.Top,
            Height = 34,
            Text = "Extract evidence",
            Font = new Font(SystemFonts.DefaultFont, FontStyle.Bold),
        };
        _dumpButton.Click += OnDump;
        _tips.SetToolTip(_dumpButton, DumpToolTip);

        _interferenceButton = new Button
        {
            Dock = DockStyle.Top,
            Height = 30,
            Text = "Interference",
        };
        _interferenceButton.Click += OnInterference;
        _tips.SetToolTip(_interferenceButton, InterferenceToolTip);

        _viewBox = new ComboBox
        {
            Dock = DockStyle.Top,
            DropDownStyle = ComboBoxStyle.DropDownList,
        };
        _viewBox.Items.AddRange(new object[] { "iso", "front", "top", "right", "fit" });
        _viewBox.SelectedIndex = 0;

        _captureButton = new Button
        {
            Dock = DockStyle.Top,
            Height = 30,
            Text = "Capture selection",
        };
        _captureButton.Click += OnCapture;
        _tips.SetToolTip(_captureButton, CaptureToolTip);

        _status = new Label
        {
            Dock = DockStyle.Fill,
            Text = "Open an assembly, choose an output folder, then Extract evidence.",
            AutoSize = false,
            Padding = new Padding(0, 8, 0, 0),
        };

        Padding = new Padding(8);
        MinimumSize = new Size(220, 260);

        // Added last-to-first: DockStyle.Top stacks in reverse order of addition.
        Controls.Add(_status);
        Controls.Add(_captureButton);
        Controls.Add(_viewBox);
        Controls.Add(_interferenceButton);
        Controls.Add(_dumpButton);
        Controls.Add(browse);
        Controls.Add(_outputBox);
    }

    /// <summary>What <b>Extract evidence</b> writes, in the words an engineer uses.</summary>
    public const string DumpToolTip =
        "Writes package.json, the evidence package describing the open document (components, "
        + "mates, holes, fasteners, geometry). The reviewer and the Ask tab read this file "
        + "instead of the live model.";

    /// <summary>What <b>Interference</b> adds to that same file.</summary>
    public const string InterferenceToolTip =
        "Adds interference results to the evidence package.";

    /// <summary>What <b>Capture selection</b> adds to it.</summary>
    public const string CaptureToolTip =
        "Adds a screenshot of the current selection to the evidence package.";

    /// <summary>Raised when the user asks for a dump. The add-in does the SOLIDWORKS work.</summary>
    public event EventHandler<string>? DumpRequested;

    /// <summary>Raised by <b>Interference</b>; the argument is the output folder.</summary>
    public event EventHandler<string>? InterferenceRequested;

    /// <summary>
    /// Raised by <b>Capture selection</b>. The argument carries the folder and the named view,
    /// because the panel owns the view list and the add-in owns SOLIDWORKS.
    /// </summary>
    public event EventHandler<CaptureRequest>? CaptureRequested;

    /// <summary>The <c>--view</c> value the drop-down is showing.</summary>
    public string SelectedView => (_viewBox.SelectedItem as string) ?? "iso";

    /// <summary>The folder package.json and meshes/ go into.</summary>
    public string OutputDirectory
    {
        get => _outputBox.Text.Trim();
        set => _outputBox.Text = value;
    }

    /// <summary>The tooltip on one of this panel's controls, as the engineer sees it.</summary>
    public string ToolTipFor(Control control) => _tips.GetToolTip(control);

    /// <summary>
    /// Offers <paramref name="folder"/> as the output folder, unless the engineer has chosen
    /// one.
    ///
    /// The session's run folder is almost always the right answer - interference and capture
    /// append to the package.json the Review or Ask tab already wrote there - but it is a
    /// suggestion, not a setting: a box the engineer typed into, or browsed to, is left exactly
    /// as it is, and so is one this panel has already suggested and had changed.
    ///
    /// <b>No folder withdraws the suggestion</b> rather than leaving the last one standing. The
    /// pane passes null when there is nowhere it can honestly point - a session folder that has
    /// gone, or a Model check folder a full extract would overwrite (T084) - and a box still
    /// showing the previous answer would be the pane pointing at it anyway.
    /// </summary>
    public void SuggestOutputDirectory(string? folder)
    {
        string current = OutputDirectory;
        bool ours = current.Length == 0
            || string.Equals(current, _suggested, StringComparison.OrdinalIgnoreCase);
        if (!ours)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(folder))
        {
            OutputDirectory = string.Empty;
            _suggested = null;
            return;
        }

        OutputDirectory = folder!;
        _suggested = folder;
    }

    /// <summary>Shows one line of progress and repaints, since the STA thread is busy.</summary>
    public void ShowProgress(string message)
    {
        _status.ForeColor = SystemColors.ControlText;
        _status.Text = message;
        _status.Refresh();
    }

    /// <summary>Shows the finished result.</summary>
    public void ShowResult(string message)
    {
        _status.ForeColor = Color.FromArgb(0, 100, 0);
        _status.Text = message;
    }

    /// <summary>Shows the failure both in the panel and in a dialog the user cannot miss.</summary>
    public void ShowError(string message, Exception error)
    {
        _status.ForeColor = Color.FromArgb(160, 0, 0);
        _status.Text = message;

        MessageBox.Show(
            this,
            message + Environment.NewLine + Environment.NewLine + error.Message,
            "SwReview: dump failed",
            MessageBoxButtons.OK,
            MessageBoxIcon.Error);
    }

    /// <summary>Enables or disables the buttons so a second run cannot start mid-run.</summary>
    public void SetBusy(bool busy)
    {
        _dumpButton.Enabled = !busy;
        _interferenceButton.Enabled = !busy;
        _captureButton.Enabled = !busy;
        Cursor = busy ? Cursors.WaitCursor : Cursors.Default;
    }

    private void OnBrowse(object sender, EventArgs e)
    {
        using (var dialog = new FolderBrowserDialog { Description = "Where should package.json be written?" })
        {
            if (dialog.ShowDialog(this) == DialogResult.OK)
            {
                OutputDirectory = dialog.SelectedPath;
            }
        }
    }

    private void OnDump(object sender, EventArgs e)
    {
        if (!HasOutputDirectory())
        {
            return;
        }

        DumpRequested?.Invoke(this, OutputDirectory);
    }

    private void OnInterference(object sender, EventArgs e)
    {
        if (!HasOutputDirectory())
        {
            return;
        }

        InterferenceRequested?.Invoke(this, OutputDirectory);
    }

    private void OnCapture(object sender, EventArgs e)
    {
        if (!HasOutputDirectory())
        {
            return;
        }

        CaptureRequested?.Invoke(this, new CaptureRequest(OutputDirectory, SelectedView));
    }

    private bool HasOutputDirectory()
    {
        if (OutputDirectory.Length != 0)
        {
            return true;
        }

        ShowProgress("Choose an output folder first.");
        return false;
    }
}

/// <summary>What <b>Capture selection</b> asks for: where to write, and which camera view.</summary>
public sealed class CaptureRequest : EventArgs
{
    public CaptureRequest(string outputDirectory, string view)
    {
        OutputDirectory = outputDirectory;
        View = view;
    }

    public string OutputDirectory { get; }

    /// <summary>One of iso, front, top, right, fit.</summary>
    public string View { get; }
}
