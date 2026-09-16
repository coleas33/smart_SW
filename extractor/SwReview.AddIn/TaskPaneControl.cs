using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using SwReview.AddIn.Review;

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
    /// The folder mapped as `https://swreview.invalid`. Defaults to `web` beside the add-in,
    /// which is where SwReview.AddIn.csproj copies both pages.
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

    private static string DefaultWebFolder() =>
        Path.Combine(Path.GetDirectoryName(typeof(TaskPaneOptions).Assembly.Location) ?? ".", "web");
}

/// <summary>
/// The Task Pane: <b>Review</b> (the chat page in WebView2), <b>Ask</b> (the CLI terminal,
/// US3) and <b>Extract</b> (the three buttons that write an evidence package by hand).
///
/// The tabs are named for what the engineer gets, not for what the code does, and each one
/// carries the same sentence twice - as a banner across the top of the tab and as the tab's
/// tooltip - because a pane whose three tabs are nouns tells a first-time user nothing about
/// which of them to press. Above all three is the <see cref="StepStrip"/>: open a document,
/// extract evidence, review or ask, each done or pending with the reason. None of this is
/// decoration; every one of these sentences replaces a question the pane was being asked.
///
/// Four rules live here because nowhere else can enforce them:
///
/// <b>One environment for the process.</b> <see cref="EnvironmentAsync"/> creates it once and
/// hands the same task to every caller, so the Review and Ask tabs share one browser
/// process over one user data folder. Two environments over the same folder with different
/// options fail at runtime (contracts/pane-host-messages.md).
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
    /// <summary>The fixed virtual host both pages are served from (pane-host-messages.md).</summary>
    public const string VirtualHostName = "swreview.invalid";

    /// <summary>The page origin, and the origin the backend is started with.</summary>
    public const string PageOrigin = "https://swreview.invalid";

    /// <summary>The Review page inside the mapped folder.</summary>
    public const string ReviewPageUrl = PageOrigin + "/Review/ReviewPage/index.html";

    /// <summary>The Ask tab's terminal page inside the same mapped folder (T060).</summary>
    public const string TerminalPageUrl = PageOrigin + "/Terminal/TerminalPage/index.html";

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

    private readonly TaskPaneOptions _options;
    private readonly TabControl _tabs;
    private readonly TabPage _reviewTab;
    private readonly TabPage _terminalTab;
    private readonly ActionsPanel _actions;
    private readonly StepStrip _steps;

    private Task<CoreWebView2Environment>? _environment;
    private WebView2? _reviewView;
    private WebView2? _terminalView;
    private bool _initializing;

    /// <summary>The terminal-first run folder this pane created, once it has created one.</summary>
    private string? _terminalRunFolder;

    public TaskPaneControl(TaskPaneOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));

        _reviewTab = NewTab("Review", ReviewPurpose, Note("Starting the review page..."));
        _terminalTab = NewTab("Ask", AskPurpose, Note("Starting the Ask page..."));

        _actions = new ActionsPanel();
        TabPage actionsTab = NewTab("Extract", ExtractPurpose, _actions);
        actionsTab.Padding = new Padding(6);

        _tabs = new TabControl { Dock = DockStyle.Fill, ShowToolTips = true };
        _tabs.TabPages.Add(_reviewTab);
        _tabs.TabPages.Add(_terminalTab);
        _tabs.TabPages.Add(actionsTab);

        _steps = new StepStrip { Dock = DockStyle.Top };

        MinimumSize = new Size(260, 320);

        // The tabs first and the strip second: WinForms docks the last-added control first, so
        // the strip added after the Fill takes its band off the top and the tabs get the rest.
        Controls.Add(_tabs);
        Controls.Add(_steps);

        // Switching tabs is the moment an engineer is looking at the strip, and it costs a
        // file-exists check; the add-in refreshes it from the events that actually change it.
        _tabs.SelectedIndexChanged += (sender, args) => RefreshSteps();

        ReviewChannel = new PageChannel(this, () => _reviewView);
        TerminalChannel = new PageChannel(this, () => _terminalView);

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

    /// <summary>Whether the Review page is loaded (false on a workstation with no runtime).</summary>
    public bool ReviewPageReady => _reviewView != null && _reviewView.CoreWebView2 != null;

    /// <summary>Whether the Terminal page is loaded.</summary>
    public bool TerminalPageReady => _terminalView != null && _terminalView.CoreWebView2 != null;

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
    /// Loads one page into one tab. Both tabs go through here so neither can be given a weaker
    /// set of guards than the other: they share a browser process and a page origin, so a
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
        core.SetVirtualHostNameToFolderMapping(
            VirtualHostName, _options.WebFolder, CoreWebView2HostResourceAccessKind.Allow);

        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.IsSwipeNavigationEnabled = false;

        core.NavigationStarting += OnNavigationStarting;
        core.NewWindowRequested += OnNewWindowRequested;
        core.WebMessageReceived += onMessage;

        core.Navigate(url);
        return view;
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

        _steps.Show(document, evidence);

        try
        {
            _actions.SuggestOutputDirectory(SessionRunDirectory);
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
            "The Microsoft Edge WebView2 runtime is not available, so the Review and Ask "
            + "tabs cannot be shown. The Extract tab still works."));

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
/// It decides nothing. The two facts it renders are answered by the add-in through
/// <see cref="TaskPaneOptions.DocumentPresent"/> and
/// <see cref="TaskPaneOptions.EvidencePresent"/>, which is what makes it testable with no
/// SOLIDWORKS and no WebView2 at all.
/// </summary>
public sealed class StepStrip : UserControl
{
    /// <summary>Said of every step that is not blocked: the same word in all three rows.</summary>
    public const string Ready = "ready";

    /// <summary>Why step 1 - and everything after it - is pending.</summary>
    public const string NoDocument = "no document open";

    /// <summary>Why step 2 is pending. "This session" is the pane's current run folder.</summary>
    public const string NoEvidence = "no evidence for this session yet";

    private static readonly Color DoneColor = Color.FromArgb(0, 100, 0);

    private readonly Label _document;
    private readonly Label _evidence;
    private readonly Label _work;

    public StepStrip()
    {
        _work = Row();
        _evidence = Row();
        _document = Row();

        AutoSize = true;
        AutoSizeMode = AutoSizeMode.GrowAndShrink;
        Padding = new Padding(6, 4, 6, 4);

        // Added last-to-first: DockStyle.Top stacks in reverse order of addition.
        Controls.Add(_work);
        Controls.Add(_evidence);
        Controls.Add(_document);

        Show(document: false, evidence: false);
    }

    /// <summary>The three lines as they read on screen, top to bottom. The tests' whole view.</summary>
    public IReadOnlyList<string> Lines => new[] { _document.Text, _evidence.Text, _work.Text };

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
    public void Show(bool document, bool evidence)
    {
        bool ready = document && evidence;

        Set(_document, "1 Open a document", document, document ? Ready : NoDocument);
        Set(_evidence, "2 Extract evidence", evidence, evidence ? Ready : NoEvidence);
        Set(_work, "3 Review or Ask", ready, ready ? Ready : (document ? NoEvidence : NoDocument));
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
    /// </summary>
    public void SuggestOutputDirectory(string? folder)
    {
        if (string.IsNullOrWhiteSpace(folder))
        {
            return;
        }

        string current = OutputDirectory;
        bool ours = current.Length == 0
            || string.Equals(current, _suggested, StringComparison.OrdinalIgnoreCase);
        if (!ours)
        {
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
