using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T080: the sixth tab.
///
/// The Task Pane grows a <b>Standards</b> tab and nothing else about it moves. That sentence is
/// the whole test: the five tabs an engineer already knows are present, unchanged, in the order
/// they were in, and Standards is sixth (FR-035). A tab that inserted itself in the middle of a
/// pane people use every day would be a regression nobody asked for, and the order is the one
/// thing about a TabControl that cannot be discovered from the screen.
///
/// The three other rules here each answer a question the pane was really asked:
///
/// <b>What is this tab for?</b> One sentence, twice - as a banner across the top of the tab and
/// as the tab's tooltip - the way every other tab in this pane says it. This one has to say
/// that it needs no AI and no key, because every other tab except Model check does, and "which
/// of these costs me a key" is the first question a first-time user has (FR-036).
///
/// <b>What does it cost at load?</b> Nothing. The tab holds a named placeholder note until it is
/// first selected, and its WebView2 is created then (FR-036). Six tabs loaded up front would
/// cost five renderer processes inside the SOLIDWORKS process before anything was pressed.
///
/// <b>Where do its messages go?</b> Its own channel and its own event, kept apart from the
/// other five for the reason they are kept apart from each other: six pages, six vocabularies,
/// and a `standards.start` answered by the review host would be answered `error` while the tab
/// waited.
///
/// What happens when WebView2 is missing is <see cref="WebViewFallbackTests"/>'s half.
/// </summary>
public sealed class TaskPaneControlTests
{
    private const string RunRoot = @"C:\SwReviewRuns";

    /// <summary>
    /// Tab 6 (contracts/standards-check.md). Written out literally rather than read from the
    /// control: the sentence is the decision, and a test that read it from the product would
    /// agree with any wording at all.
    /// </summary>
    private const string StandardsPurpose =
        "Check the open part, assembly or drawing against this workstation's release standards "
        + "in seconds, and see whether it is ready to release. No AI, no key; read-only.";

    // ---- the order -------------------------------------------------------------------------

    [Fact]
    public void TheSixTabsAreInTheOrderTheContractsNameWithStandardsSixth()
    {
        WithPane(pane =>
        {
            string[] captions = Tabs(pane).Select(tab => tab.Text).ToArray();

            Assert.Equal(
                new[] { "Review", "Extract", "Model check", "Remodel", "Standards" },
                captions);
        });
    }

    /// <summary>
    /// The Ask tab is hidden, not removed: the pane has no tab by that name, loads no terminal
    /// page, and the switch that decides it is the one documented on the control. Turning the
    /// terminal back on is that one value, and this test is the one that changes with it.
    /// </summary>
    [Fact]
    public void TheAskTabIsHiddenWhileTheTerminalIsNotPartOfThePilot()
    {
        Assert.False(TaskPaneControl.AskTabShown, "AskTabShown is on; update the tab inventories.");

        WithPane(pane =>
        {
            Assert.DoesNotContain("Ask", Tabs(pane).Select(tab => tab.Text));
            Assert.False(pane.TerminalPageReady, "The terminal page was loaded for a hidden tab.");
        });
    }

    /// <summary>
    /// No existing tab moves and none is hidden. The first four are asserted as a prefix rather
    /// than by count, so a tab added later does not silently reorder these four. (Ask is the
    /// one deliberate exception, hidden by <see cref="TaskPaneControl.AskTabShown"/>.)
    /// </summary>
    [Fact]
    public void NoExistingTabMovedAndNoneIsHidden()
    {
        WithPane(pane =>
        {
            TabPage[] tabs = Tabs(pane).ToArray();

            Assert.Equal(
                new[] { "Review", "Extract", "Model check", "Remodel" },
                tabs.Take(4).Select(tab => tab.Text).ToArray());

            // None of them is hidden or switched off: the sixth tab is added beside the five,
            // never in place of one (FR-035).
            foreach (TabPage tab in tabs)
            {
                Assert.True(tab.Enabled, $"The {tab.Text} tab is disabled.");
            }
        });
    }

    // ---- what the tab is for -----------------------------------------------------------------

    [Fact]
    public void TheStandardsTabSaysWhatItIsForInABannerAndInItsTooltip()
    {
        WithPane(pane =>
        {
            TabPage tab = TabNamed(pane, "Standards");

            Assert.Equal(StandardsPurpose, tab.ToolTipText);
            Assert.True(
                Descendants(tab).Any(
                    control => string.Equals(control.Text, StandardsPurpose, StringComparison.Ordinal)),
                "The Standards tab shows no purpose banner. It shows:"
                    + Environment.NewLine + TextOf(tab));
        });
    }

    /// <summary>
    /// "No AI, no key" is the sentence engineers ask for first, because every tab in this pane
    /// except Model check needs one (FR-036). It is on the banner rather than in a dialog they
    /// would dismiss.
    /// </summary>
    [Fact]
    public void TheStandardsPurposeSaysItNeedsNoAiAndNoKey()
    {
        Assert.Contains("No AI, no key", StandardsPurpose, StringComparison.Ordinal);
        Assert.Contains("read-only", StandardsPurpose, StringComparison.Ordinal);

        WithPane(pane =>
            Assert.Contains("No AI, no key", TabNamed(pane, "Standards").ToolTipText));
    }

    // ---- what it costs at load -------------------------------------------------------------------

    /// <summary>
    /// The tab's content is a named placeholder note until it is first selected. Three of the
    /// six tabs are now lazy; a session that opens none of them pays for none of them.
    /// </summary>
    [Fact]
    public void TheStandardsTabHoldsItsPlaceholderNoteUntilItIsFirstActivated()
    {
        WithPane(pane =>
        {
            TabPage tab = TabNamed(pane, "Standards");

            Assert.Contains(TaskPaneControl.StandardsPending, TextOf(tab));
            Assert.False(
                pane.StandardsPageReady,
                "The Standards page was loaded at add-in load rather than on first activation.");
            Assert.Empty(Descendants(tab).OfType<Microsoft.Web.WebView2.WinForms.WebView2>());
        });
    }

    [Fact]
    public void TheStandardsPageUrlIsOnThePanesOwnVirtualHost()
    {
        Assert.Equal(
            "https://swreview.invalid/Standards/StandardsPage/index.html",
            TaskPaneControl.StandardsPageUrl);
        Assert.StartsWith(
            TaskPaneControl.PageOrigin + "/", TaskPaneControl.StandardsPageUrl, StringComparison.Ordinal);
    }

    // ---- where its messages go ---------------------------------------------------------------------

    /// <summary>
    /// The sixth channel exists before the page does and drops what it cannot deliver: a host
    /// message posted to a tab nobody has opened is not an error, it is a message with nowhere
    /// to go (see <c>IPageChannel</c>).
    /// </summary>
    [Fact]
    public void TheStandardsChannelExistsBeforeThePageDoesAndPostsNothingIntoNothing()
    {
        WithPane(pane =>
        {
            Assert.NotNull(pane.StandardsChannel);
            Assert.NotSame(pane.StandardsChannel, pane.ModelCheckChannel);

            Exception? escaped = Record.Exception(
                () => pane.StandardsChannel.PostMessage(
                    "{\"type\":\"status\",\"payload\":{\"stage\":\"ready\"}}"));

            Assert.True(escaped == null, "Posting to an unopened Standards tab threw: " + escaped);
        });
    }

    /// <summary>
    /// Six pages, six vocabularies: the Standards page's messages are raised on their own event
    /// rather than tagged onto another page's, so a `standards.start` never reaches a host that
    /// would answer it `error` while the tab waited.
    /// </summary>
    [Fact]
    public void TheStandardsPageHasItsOwnMessageEvent()
    {
        Assert.NotNull(
            typeof(TaskPaneControl).GetEvent(nameof(TaskPaneControl.StandardsPageMessageReceived)));

        var names = new HashSet<string>(
            typeof(TaskPaneControl).GetEvents().Select(raised => raised.Name), StringComparer.Ordinal);

        foreach (string existing in new[]
        {
            nameof(TaskPaneControl.PageMessageReceived),
            nameof(TaskPaneControl.TerminalPageMessageReceived),
            nameof(TaskPaneControl.ModelCheckPageMessageReceived),
            nameof(TaskPaneControl.RemodelPageMessageReceived),
        })
        {
            Assert.Contains(existing, names);
        }
    }

    // ---- the pane ------------------------------------------------------------------------------------

    private static void WithPane(Action<TaskPaneControl> assertions)
    {
        var options = new TaskPaneOptions(new UnusedEnvironmentFactory(), RunRoot);

        StaHost.Run(form =>
        {
            using (var control = new TaskPaneControl(options))
            {
                control.Dock = DockStyle.Fill;
                form.Controls.Add(control);

                assertions(control);
            }

            return Task.CompletedTask;
        });
    }

    private static IEnumerable<TabPage> Tabs(Control root) =>
        Descendants(root).OfType<TabControl>().Single().TabPages.Cast<TabPage>();

    private static TabPage TabNamed(Control root, string caption)
    {
        TabPage? tab = Tabs(root)
            .FirstOrDefault(candidate => string.Equals(candidate.Text, caption, StringComparison.Ordinal));

        Assert.True(tab != null, $"There is no \"{caption}\" tab.");
        return tab!;
    }

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

    /// <summary>A factory the pane never calls: nothing here initializes WebView2.</summary>
    private sealed class UnusedEnvironmentFactory : IWebViewEnvironmentFactory
    {
        public Task<CoreWebView2Environment> CreateAsync() =>
            throw new InvalidOperationException("TaskPaneControlTests never initializes WebView2.");
    }
}
