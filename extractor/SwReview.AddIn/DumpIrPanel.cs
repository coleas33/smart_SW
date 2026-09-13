using System;
using System.Drawing;
using System.Windows.Forms;

namespace SwReview.AddIn;

/// <summary>
/// The Task Pane control: a folder to write to, the three buttons contracts/cli.md names -
/// <b>Dump IR</b> (T060), <b>Interference</b> and <b>Capture selection</b> (T076) - and a
/// status line. Deliberately plain WinForms with no designer file; the whole UI is seven
/// controls, and a .Designer.cs would be more code than the panel.
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
public sealed class DumpIrPanel : UserControl
{
    private readonly Button _dumpButton;
    private readonly Button _interferenceButton;
    private readonly Button _captureButton;
    private readonly ComboBox _viewBox;
    private readonly TextBox _outputBox;
    private readonly Label _status;

    public DumpIrPanel()
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

    /// <summary>Raised by <b>Interference</b> (T076); the argument is the output folder.</summary>
    public event EventHandler<string>? InterferenceRequested;

    /// <summary>
    /// Raised by <b>Capture selection</b> (T076). The argument carries the folder and the
    /// named view, because the panel owns the view list and the add-in owns SOLIDWORKS.
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
