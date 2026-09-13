using System;
using System.Drawing;
using System.Windows.Forms;

namespace SwReview.AddIn;

/// <summary>
/// The Task Pane control: a Dump IR button, a folder to write to, and a status line.
/// Deliberately plain WinForms with no designer file - the whole UI is five controls, and
/// a .Designer.cs would be more code than the panel.
///
/// The dump runs on THIS thread, which is the SOLIDWORKS application STA thread. A worker
/// thread would be smoother but would have to marshal every COM call back here anyway
/// (constitution, Technical Constraints), so the button disables itself and the status
/// line reports progress instead.
/// </summary>
public sealed class DumpIrPanel : UserControl
{
    private readonly Button _dumpButton;
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

        _status = new Label
        {
            Dock = DockStyle.Fill,
            Text = "Open an assembly, choose a folder, then Dump IR.",
            AutoSize = false,
            Padding = new Padding(0, 8, 0, 0),
        };

        Padding = new Padding(8);
        MinimumSize = new Size(220, 160);

        // Added last-to-first: DockStyle.Top stacks in reverse order of addition.
        Controls.Add(_status);
        Controls.Add(_dumpButton);
        Controls.Add(browse);
        Controls.Add(_outputBox);
    }

    /// <summary>Raised when the user asks for a dump. The add-in does the SOLIDWORKS work.</summary>
    public event EventHandler<string>? DumpRequested;

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

    /// <summary>Enables or disables the button so a second dump cannot start mid-run.</summary>
    public void SetBusy(bool busy)
    {
        _dumpButton.Enabled = !busy;
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
        if (OutputDirectory.Length == 0)
        {
            ShowProgress("Choose an output folder first.");
            return;
        }

        DumpRequested?.Invoke(this, OutputDirectory);
    }
}
