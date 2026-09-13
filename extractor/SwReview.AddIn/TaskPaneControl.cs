using System;
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

    private static string DefaultWebFolder() =>
        Path.Combine(Path.GetDirectoryName(typeof(TaskPaneOptions).Assembly.Location) ?? ".", "web");
}

/// <summary>
/// The Task Pane: <b>Review</b> (the chat page in WebView2), <b>Terminal</b> (US3) and
/// <b>Actions</b> (the three buttons that write an evidence package by hand).
///
/// Four rules live here because nowhere else can enforce them:
///
/// <b>One environment for the process.</b> <see cref="EnvironmentAsync"/> creates it once and
/// hands the same task to every caller, so the Review and Terminal tabs share one browser
/// process over one user data folder. Two environments over the same folder with different
/// options fail at runtime (contracts/pane-host-messages.md).
///
/// <b>Nothing thrown here reaches SOLIDWORKS.</b> <see cref="InitializeAsync"/> never throws.
/// The add-in is loaded in-process and an exception out of a Task Pane control on the
/// application thread is SOLIDWORKS' problem, not ours; a missing runtime ends as a panel that
/// says what to install and where the run folder is, with the Actions tab still working.
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

    /// <summary>Where the Evergreen runtime comes from, shown when it is missing.</summary>
    public const string RuntimeDownloadUrl = "https://developer.microsoft.com/en-us/microsoft-edge/webview2/";

    private readonly TaskPaneOptions _options;
    private readonly TabControl _tabs;
    private readonly TabPage _reviewTab;
    private readonly TabPage _terminalTab;
    private readonly ActionsPanel _actions;

    private Task<CoreWebView2Environment>? _environment;
    private WebView2? _reviewView;
    private bool _initializing;

    public TaskPaneControl(TaskPaneOptions options)
    {
        _options = options ?? throw new ArgumentNullException(nameof(options));

        _reviewTab = new TabPage("Review") { Padding = new Padding(0), UseVisualStyleBackColor = true };
        _reviewTab.Controls.Add(Note("Starting the review page..."));

        _terminalTab = new TabPage("Terminal") { Padding = new Padding(6), UseVisualStyleBackColor = true };
        _terminalTab.Controls.Add(Note(
            "The CLI terminal arrives with the terminal tab. Until then, run the CLI in a "
            + "console window."));

        _actions = new ActionsPanel { Dock = DockStyle.Fill };
        var actionsTab = new TabPage("Actions") { Padding = new Padding(6), UseVisualStyleBackColor = true };
        actionsTab.Controls.Add(_actions);

        _tabs = new TabControl { Dock = DockStyle.Fill };
        _tabs.TabPages.Add(_reviewTab);
        _tabs.TabPages.Add(_terminalTab);
        _tabs.TabPages.Add(actionsTab);

        MinimumSize = new Size(260, 320);
        Controls.Add(_tabs);

        ReviewChannel = new PageChannel(this);
    }

    /// <summary>The three buttons: Dump IR, Interference, Capture selection.</summary>
    public ActionsPanel Actions => _actions;

    /// <summary>Posts host messages to the Review page, from any thread.</summary>
    public IPageChannel ReviewChannel { get; }

    /// <summary>
    /// One `{type, id, payload}` document from the Review page, raised on the UI thread. The
    /// add-in hands it to <see cref="ReviewHost"/> off this thread and one at a time.
    /// </summary>
    public event EventHandler<string>? PageMessageReceived;

    /// <summary>Whether the Review page is loaded (false on a workstation with no runtime).</summary>
    public bool ReviewPageReady => _reviewView != null && _reviewView.CoreWebView2 != null;

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
    /// fallback panel, and the Actions tab keeps working.
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

            await AttachReviewPageAsync(environment).ConfigureAwait(true);
        }
        catch (Exception failure)
        {
            ShowFallback(failure);
        }
    }

    private async Task AttachReviewPageAsync(CoreWebView2Environment environment)
    {
        var view = new WebView2 { Dock = DockStyle.Fill };
        _reviewTab.Controls.Clear();
        _reviewTab.Controls.Add(view);
        _reviewView = view;

        await view.EnsureCoreWebView2Async(environment).ConfigureAwait(true);

        CoreWebView2 core = view.CoreWebView2;
        core.SetVirtualHostNameToFolderMapping(
            VirtualHostName, _options.WebFolder, CoreWebView2HostResourceAccessKind.Allow);

        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.IsSwipeNavigationEnabled = false;

        core.NavigationStarting += OnNavigationStarting;
        core.NewWindowRequested += OnNewWindowRequested;
        core.WebMessageReceived += OnWebMessageReceived;

        core.Navigate(ReviewPageUrl);
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

    private void OnWebMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e)
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

        PageMessageReceived?.Invoke(this, json);
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
        Fill(_reviewTab, BuildFallback(failure));
        Fill(_terminalTab, BuildFallback(failure));
    }

    private static void Fill(TabPage page, Control content)
    {
        page.Controls.Clear();
        page.Controls.Add(content);
    }

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
            "The Microsoft Edge WebView2 runtime is not available, so the Review and Terminal "
            + "tabs cannot be shown. The Actions tab still works."));

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

    /// <summary>The real <see cref="IPageChannel"/>: marshals onto the pane, then posts.</summary>
    private sealed class PageChannel : IPageChannel
    {
        private readonly TaskPaneControl _pane;

        public PageChannel(TaskPaneControl pane)
        {
            _pane = pane;
        }

        public void PostMessage(string json) => _pane.PostToPage(json);
    }

    private void PostToPage(string json)
    {
        if (json == null || IsDisposed || !IsHandleCreated)
        {
            return;
        }

        try
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action<string>(PostOnUiThread), json);
                return;
            }

            PostOnUiThread(json);
        }
        catch (Exception)
        {
            // The pane closed between the check and the call. There is nobody left to tell.
        }
    }

    private void PostOnUiThread(string json)
    {
        WebView2? view = _reviewView;
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
            WebView2? view = _reviewView;
            _reviewView = null;
            view?.Dispose();
        }

        base.Dispose(disposing);
    }
}

/// <summary>
/// The Actions tab: a folder to write to, the three buttons contracts/cli.md names -
/// <b>Dump IR</b>, <b>Interference</b> and <b>Capture selection</b> - and a status line.
/// Deliberately plain WinForms with no designer file; the whole UI is seven controls, and a
/// .Designer.cs would be more code than the panel.
///
/// Everything runs on THIS thread, which is the SOLIDWORKS application STA thread. A worker
/// thread would be smoother but would have to marshal every COM call back here anyway
/// (constitution, Technical Constraints), so the buttons disable themselves and the status
/// line reports progress instead.
///
/// All three buttons write into the same folder, because interference and capture append to
/// the package.json that Dump IR wrote there: the results have to sit next to the components
/// they name.
/// </summary>
public sealed class ActionsPanel : UserControl
{
    private readonly Button _dumpButton;
    private readonly Button _interferenceButton;
    private readonly Button _captureButton;
    private readonly ComboBox _viewBox;
    private readonly TextBox _outputBox;
    private readonly Label _status;

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
            Text = "Dump IR",
            Font = new Font(SystemFonts.DefaultFont, FontStyle.Bold),
        };
        _dumpButton.Click += OnDump;

        _interferenceButton = new Button
        {
            Dock = DockStyle.Top,
            Height = 30,
            Text = "Interference",
        };
        _interferenceButton.Click += OnInterference;

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

        _status = new Label
        {
            Dock = DockStyle.Fill,
            Text = "Open an assembly, choose a folder, then Dump IR.",
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
