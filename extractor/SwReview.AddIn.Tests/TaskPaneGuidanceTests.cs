using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;
using SwReview.AddIn.Terminal;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// What the Task Pane tells an engineer who has never seen it before.
///
/// Everything asserted here is text on the screen, and it is written out literally rather
/// than compared against the product's own constants: the sentences are the decision, so a
/// test that read them from the control would agree with any wording at all.
///
/// Three rules, and each of them was a real complaint about the pane before this test existed:
///
/// <b>The tabs are named for the engineer's job, not ours.</b> "Terminal" and "Actions" say
/// what the code does; <b>Review</b>, <b>Ask</b> and <b>Extract</b> say what the engineer gets.
///
/// <b>Nothing says IR.</b> "Dump IR" is our word for the evidence package and means nothing at
/// a workstation. The sweep at the bottom of this file walks every caption, banner, status line
/// and tooltip the pane can show and fails on the word, wherever it comes back.
///
/// <b>The order is visible.</b> The step strip sits above the tabs and is always there:
/// open a document, extract evidence, then review or ask - each of them done or pending, with
/// the reason it is pending, so "the Review button did nothing" has an answer on screen.
/// </summary>
public sealed class TaskPaneGuidanceTests
{
    private const string RunRoot = @"C:\SwReviewRuns";

    private const string ReviewPurpose =
        "Automated design review of the open assembly: press Review to extract evidence, run "
        + "the reviewer, and discuss its findings. Provider, model, and API key live under "
        + "Settings.";

    private const string AskPurpose =
        "Ask Codex anything about the open model. Read-only: it can query the extracted "
        + "evidence, measure, and capture, but cannot change or save anything.";

    private const string ExtractPurpose =
        "Manual extraction for the command line: write package.json, the evidence package "
        + "describing the open document (components, mates, holes, fasteners, geometry), add "
        + "interference results, capture the current selection. The Review tab does this for "
        + "you automatically.";

    // ---- the tabs ------------------------------------------------------------------------

    [Fact]
    public void TheTabsAreNamedForWhatTheEngineerWantsToDo()
    {
        WithPane((pane, options) =>
        {
            string[] captions = Tabs(pane).Select(tab => tab.Text).ToArray();

            Assert.Equal(new[] { "Review", "Ask", "Extract" }, captions);
        });
    }

    [Fact]
    public void EachTabSaysWhatItIsForInABannerAndInItsTooltip()
    {
        WithPane((pane, options) =>
        {
            TabControl tabs = Descendants(pane).OfType<TabControl>().Single();

            Assert.True(tabs.ShowToolTips, "The tab tooltips are switched off, so nobody sees them.");

            var expected = new Dictionary<string, string>
            {
                { "Review", ReviewPurpose },
                { "Ask", AskPurpose },
                { "Extract", ExtractPurpose },
            };

            foreach (TabPage tab in Tabs(pane))
            {
                string purpose = expected[tab.Text];

                Assert.Equal(purpose, tab.ToolTipText);
                Assert.True(
                    Descendants(tab).Any(control => string.Equals(control.Text, purpose, StringComparison.Ordinal)),
                    $"The {tab.Text} tab shows no purpose banner. It shows:"
                        + Environment.NewLine + TextOf(tab));
            }
        });
    }

    // ---- the step strip ------------------------------------------------------------------

    [Fact]
    public void TheStepStripIsAboveTheTabsAndIsAlwaysThere()
    {
        WithPane((pane, options) =>
        {
            StepStrip strip = Assert.Single(pane.Controls.OfType<StepStrip>());

            Assert.Same(pane.Steps, strip);
            Assert.Equal(DockStyle.Top, strip.Dock);
            Assert.True(strip.Visible, "The step strip is hidden, so the order is invisible again.");

            // Above, not below: the strip is docked Top and the tabs fill what is left, and
            // WinForms docks the last-added control first - so the strip must come after.
            Assert.True(
                pane.Controls.IndexOf(strip) > pane.Controls.IndexOf(
                    Descendants(pane).OfType<TabControl>().Single()),
                "The step strip is docked below the tabs.");
        });
    }

    [Fact]
    public void WithNothingOpenEveryStepIsPendingAndSaysWhy()
    {
        WithPane((pane, options) =>
        {
            options.DocumentPresent = () => false;
            options.EvidencePresent = () => false;
            pane.RefreshSteps();

            Assert.Equal(
                new[]
                {
                    "1 Open a document - pending: no document open",
                    "2 Extract evidence - pending: no evidence for this session yet",
                    "3 Review or Ask - pending: no document open",
                },
                pane.Steps.Lines.ToArray());
        });
    }

    [Fact]
    public void WithADocumentOpenOnlyTheEvidenceIsMissing()
    {
        WithPane((pane, options) =>
        {
            options.DocumentPresent = () => true;
            options.EvidencePresent = () => false;
            pane.RefreshSteps();

            Assert.Equal(
                new[]
                {
                    "1 Open a document - done: ready",
                    "2 Extract evidence - pending: no evidence for this session yet",
                    "3 Review or Ask - pending: no evidence for this session yet",
                },
                pane.Steps.Lines.ToArray());
        });
    }

    [Fact]
    public void WithEvidenceInTheSessionFolderEveryStepIsReady()
    {
        WithPane((pane, options) =>
        {
            options.DocumentPresent = () => true;
            options.EvidencePresent = () => true;
            pane.RefreshSteps();

            Assert.Equal(
                new[]
                {
                    "1 Open a document - done: ready",
                    "2 Extract evidence - done: ready",
                    "3 Review or Ask - done: ready",
                },
                pane.Steps.Lines.ToArray());
        });
    }

    /// <summary>
    /// Evidence in the folder and no document open - the engineer ran a review or pressed
    /// Extract evidence and then closed the model, which is an ordinary afternoon.
    ///
    /// Step 3 used to read done here, from the evidence alone, above a step 1 that said "no
    /// document open": a vacuous pass, and the exact complaint the strip was added to answer.
    /// `ReviewHost` refuses to start a review without a document, so pressing Review does
    /// nothing, and the strip had just said it would work.
    /// </summary>
    [Fact]
    public void EvidenceWithTheDocumentClosedIsNotReadyToReviewOrAsk()
    {
        WithPane((pane, options) =>
        {
            options.DocumentPresent = () => false;
            options.EvidencePresent = () => true;
            pane.RefreshSteps();

            Assert.Equal(
                new[]
                {
                    "1 Open a document - pending: no document open",
                    "2 Extract evidence - done: ready",
                    "3 Review or Ask - pending: no document open",
                },
                pane.Steps.Lines.ToArray());
        });
    }

    [Fact]
    public void ThePaneNeverThrowsBecauseAStepCallbackDid()
    {
        // Both callbacks reach into SOLIDWORKS, and this runs on the application thread.
        WithPane((pane, options) =>
        {
            options.DocumentPresent = () => throw new InvalidOperationException("no SOLIDWORKS");
            options.EvidencePresent = () => throw new InvalidOperationException("no folder");

            Exception? escaped = Record.Exception(() => pane.RefreshSteps());

            Assert.True(escaped == null, "A failing step callback reached SOLIDWORKS: " + escaped);
            Assert.Equal(3, pane.Steps.Lines.Count);
        });
    }

    // ---- the Extract tab -------------------------------------------------------------------

    [Fact]
    public void TheExtractTabOpensOnTheCurrentSessionFolder()
    {
        string first = NewFolder();
        string second = NewFolder();
        try
        {
            string? session = first;
            WithPane(
                (pane, options) =>
                {
                    pane.RefreshSteps();
                    Assert.Equal(first, pane.Actions.OutputDirectory);

                    // A session that moved on - the engineer pressed Review again - moves the
                    // suggestion with it, because the interference and capture buttons append
                    // to the package.json in that folder.
                    session = second;
                    pane.RefreshSteps();
                    Assert.Equal(second, pane.Actions.OutputDirectory);
                },
                options => options.CurrentSessionRunDirectory = () => session);
        }
        finally
        {
            Delete(first);
            Delete(second);
        }
    }

    [Fact]
    public void AFolderTheEngineerChoseIsNeverOverwrittenBySuggestion()
    {
        string session = NewFolder();
        try
        {
            WithPane(
                (pane, options) =>
                {
                    pane.RefreshSteps();
                    pane.Actions.OutputDirectory = @"D:\somewhere-else";

                    pane.RefreshSteps();

                    Assert.Equal(@"D:\somewhere-else", pane.Actions.OutputDirectory);
                },
                options => options.CurrentSessionRunDirectory = () => session);
        }
        finally
        {
            Delete(session);
        }
    }

    [Fact]
    public void TheExtractButtonsSayWhatTheyWriteRatherThanNamingTheDumpFormat()
    {
        WithPane((pane, options) =>
        {
            ActionsPanel panel = pane.Actions;

            Assert.Equal(
                "Writes package.json, the evidence package describing the open document "
                    + "(components, mates, holes, fasteners, geometry). The reviewer and the Ask "
                    + "tab read this file instead of the live model.",
                panel.ToolTipFor(ButtonNamed(panel, "Extract evidence")));
            Assert.Equal(
                "Adds interference results to the evidence package.",
                panel.ToolTipFor(ButtonNamed(panel, "Interference")));
            Assert.Equal(
                "Adds a screenshot of the current selection to the evidence package.",
                panel.ToolTipFor(ButtonNamed(panel, "Capture selection")));

            Assert.Contains(
                "Open an assembly, choose an output folder, then Extract evidence.",
                TextOf(panel));
        });
    }

    // ---- the word itself --------------------------------------------------------------------

    [Fact]
    public void NothingThePaneShowsCallsTheEvidencePackageAnIr()
    {
        WithPane((pane, options) =>
        {
            var said = new List<string>();
            foreach (Control control in Descendants(pane))
            {
                said.Add(control.Text ?? string.Empty);
                if (control is TabPage tab)
                {
                    said.Add(tab.ToolTipText ?? string.Empty);
                }
            }

            said.AddRange(
                new[] { "Extract evidence", "Interference", "Capture selection" }
                    .Select(caption => pane.Actions.ToolTipFor(ButtonNamed(pane.Actions, caption))));

            string[] offenders = said
                .Where(text => Regex.IsMatch(text ?? string.Empty, @"\bIR\b"))
                .ToArray();

            Assert.True(
                offenders.Length == 0,
                "The pane still says IR at the engineer: " + string.Join(" | ", offenders));
        });
    }

    /// <summary>
    /// The same rule where the sweep above cannot reach: the two pages, and the generated
    /// Codex instructions.
    ///
    /// The instructions matter most of the three. They are the CLI's whole system prompt, so
    /// whatever they say the CLI repeats to the engineer in its own words in the Ask tab -
    /// which is how "press Dump IR" survived every WinForms sweep in this file and reached a
    /// workstation anyway.
    ///
    /// Comments are stripped first. "The IR" is our word for the format and is all over our
    /// own source; what is banned is the word on someone's screen.
    /// </summary>
    [Fact]
    public void NoPageAndNoGeneratedProfileSaysIrEither()
    {
        var offenders = new List<string>();
        foreach (KeyValuePair<string, string> text in EngineerFacingText())
        {
            foreach (Match said in Regex.Matches(Strip(text.Value), @"^.*\bIR\b.*$", RegexOptions.Multiline))
            {
                offenders.Add(text.Key + ": " + said.Value.Trim());
            }
        }

        Assert.True(
            offenders.Count == 0,
            "The evidence package is still called an IR where an engineer reads it:"
                + Environment.NewLine + string.Join(Environment.NewLine, offenders));
    }

    /// <summary>
    /// Every button the generated instructions tell the engineer to press is a button that
    /// exists. Codex is told to hand these back verbatim - they are bold for exactly that
    /// reason - and "press Dump IR" sends an engineer looking for a control that was renamed
    /// two tabs ago.
    ///
    /// The captions are written out here rather than read from the pane, for the reason the
    /// class comment gives: a test that read them from the product would agree with any
    /// wording at all. The pane's own tests pin the same four literals.
    /// </summary>
    [Fact]
    public void TheGeneratedProfileNamesOnlyButtonsThePaneReallyShows()
    {
        var captions = new[] { "Review", "Extract evidence", "Interference", "Capture selection" };

        string[] named = Regex.Matches(CliProfileWriter.CodexInstructions, @"\*\*([^*]+)\*\*")
            .Cast<Match>()
            .Select(match => match.Groups[1].Value)
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        Assert.NotEmpty(named);

        string[] invented = named.Where(caption => !captions.Contains(caption)).ToArray();

        Assert.True(
            invented.Length == 0,
            "The generated Codex instructions tell the engineer to press a button the pane does "
                + "not have: " + string.Join(" | ", invented) + ". It shows: "
                + string.Join(" | ", captions));
    }

    /// <summary>
    /// Everything with an engineer on the other end of it that the WinForms sweep cannot see:
    /// the shipped pages, and the profile as `CliProfileWriter` writes it into the generated
    /// home (the property the writer itself writes from, so a test cannot pass over a file the
    /// product does not use).
    /// </summary>
    private static IEnumerable<KeyValuePair<string, string>> EngineerFacingText()
    {
        foreach (string path in Directory
            .GetFiles(ReviewPageFiles.WebFolder, "*.*", SearchOption.AllDirectories)
            .Where(path => path.EndsWith(".html", StringComparison.OrdinalIgnoreCase)
                || path.EndsWith(".js", StringComparison.OrdinalIgnoreCase))
            .Where(path => !path.Split(Path.DirectorySeparatorChar).Contains("vendor"))
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            yield return new KeyValuePair<string, string>(
                path.Substring(ReviewPageFiles.WebFolder.Length).TrimStart(Path.DirectorySeparatorChar),
                File.ReadAllText(path));
        }

        yield return new KeyValuePair<string, string>(
            CliProfileWriter.InstructionsFileName, CliProfileWriter.CodexInstructions);
    }

    /// <summary>Comments out: HTML, block and whole-line. A `//` inside a string literal is
    /// left alone, which is why only whole-line `//` comments go.</summary>
    private static string Strip(string source) =>
        Regex.Replace(
            Regex.Replace(
                Regex.Replace(source, @"<!--.*?-->", " ", RegexOptions.Singleline),
                @"/\*.*?\*/",
                " ",
                RegexOptions.Singleline),
            @"^[ \t]*//.*$",
            string.Empty,
            RegexOptions.Multiline);

    // ---- the pane ---------------------------------------------------------------------------

    private static void WithPane(Action<TaskPaneControl, TaskPaneOptions> assertions) =>
        WithPane(assertions, _ => { });

    /// <summary>
    /// Builds the pane on an STA thread with a factory that is never asked for anything:
    /// every assertion here is about the control WinForms builds in its constructor, which is
    /// what an engineer sees before - and whether or not - WebView2 ever starts.
    /// </summary>
    private static void WithPane(
        Action<TaskPaneControl, TaskPaneOptions> assertions, Action<TaskPaneOptions> configure)
    {
        var options = new TaskPaneOptions(new UnusedEnvironmentFactory(), RunRoot);
        configure(options);

        StaHost.Run(form =>
        {
            using (var control = new TaskPaneControl(options))
            {
                control.Dock = DockStyle.Fill;
                form.Controls.Add(control);

                assertions(control, options);
            }

            return Task.CompletedTask;
        });
    }

    private static Button ButtonNamed(Control root, string caption)
    {
        Button? button = Descendants(root)
            .OfType<Button>()
            .FirstOrDefault(candidate => string.Equals(candidate.Text, caption, StringComparison.Ordinal));

        Assert.True(button != null, $"There is no \"{caption}\" button on the Extract tab.");
        return button!;
    }

    private static IEnumerable<TabPage> Tabs(Control root) =>
        Descendants(root).OfType<TabControl>().Single().TabPages.Cast<TabPage>();

    private static string TextOf(Control root) =>
        string.Join(
            Environment.NewLine,
            Descendants(root).Select(control => control.Text).Where(text => !string.IsNullOrEmpty(text)));

    private static IEnumerable<Control> Descendants(Control root)
    {
        foreach (Control child in root.Controls)
        {
            yield return child;

            foreach (Control descendant in Descendants(child))
            {
                yield return descendant;
            }
        }
    }

    private static string NewFolder()
    {
        string folder = Path.Combine(
            Path.GetTempPath(), "SwReview.Guidance", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        return folder;
    }

    private static void Delete(string folder)
    {
        try
        {
            Directory.Delete(folder, recursive: true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    /// <summary>A factory the pane never calls, because nothing here initializes WebView2.</summary>
    private sealed class UnusedEnvironmentFactory : IWebViewEnvironmentFactory
    {
        public Task<Microsoft.Web.WebView2.Core.CoreWebView2Environment> CreateAsync() =>
            throw new InvalidOperationException(
                "TaskPaneGuidanceTests never initializes WebView2.");
    }
}
