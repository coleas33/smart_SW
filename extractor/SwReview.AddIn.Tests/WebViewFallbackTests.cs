using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T042b: a workstation with no WebView2 runtime still gets a usable Task Pane.
///
/// This is the one failure the add-in cannot be allowed to throw on. SOLIDWORKS loads the
/// add-in in-process, and an exception out of a Task Pane control on the application thread is
/// SOLIDWORKS' problem, not ours: it can take the add-in out of the session or the session out
/// of the engineer's day. So the runtime being missing has to end as a panel that says what to
/// install and where the run folder is - text the engineer can read off the screen - with the
/// Extract tab, which needs no WebView2 at all, still doing its three jobs.
///
/// The environment is the other half. contracts/pane-host-messages.md requires exactly one
/// <see cref="CoreWebView2Environment"/> per process over an explicit user data folder under
/// `%LOCALAPPDATA%`: the default folder is derived from `SLDWORKS.exe`, is shared with
/// SOLIDWORKS' own WebView2 usage and every other add-in in the process, and sits under
/// `C:\Program Files\...`, which is not writable. A second environment over a folder already
/// opened with different options fails at runtime, so "one per process, shared by both tabs" is
/// a correctness rule rather than an optimisation, and it is asserted here by counting.
///
/// <b>What T043 must provide</b> (this test is the contract, and it is deliberately small):
///
/// <code>
///   public interface IWebViewEnvironmentFactory
///   {
///       Task&lt;CoreWebView2Environment&gt; CreateAsync();
///   }
///
///   public sealed class WebViewEnvironmentFactory : IWebViewEnvironmentFactory
///   {
///       public static string UserDataFolder { get; }   // %LOCALAPPDATA%\SwReview\WebView2\&lt;instance&gt;
///   }
///
///   public sealed class TaskPaneOptions
///   {
///       public TaskPaneOptions(IWebViewEnvironmentFactory environmentFactory, string runRoot);
///   }
///
///   public sealed class TaskPaneControl : UserControl
///   {
///       public TaskPaneControl(TaskPaneOptions options);
///       public Task InitializeAsync();   // never throws; creates the environment once, up front
///   }
/// </code>
///
/// The tabs are found by their `Text` - Review, Ask, Extract, Model check - and nothing else
/// about the control's shape is assumed, so T043 keeps a free hand over layout.
/// </summary>
public sealed class WebViewFallbackTests
{
    private const string RunRoot = @"C:\SwReviewRuns";

    /// <summary>
    /// The Evergreen runtime's download page. It is asserted on because a fallback panel that
    /// says "install WebView2" without saying from where sends the engineer to IT, and IT to a
    /// search engine.
    /// </summary>
    private static readonly Regex EvergreenDownload = new Regex(
        @"https://developer\.microsoft\.com/(?:[a-z]{2}-[a-z]{2}/)?microsoft-edge/webview2/?",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    [Fact]
    public void AMissingRuntimeShowsTheDownloadUrlAndTheRunRootAsPlainText()
    {
        WithPane((control, factory) =>
        {
            string review = TextOf(TabNamed(control, "Review"));

            Assert.True(
                EvergreenDownload.IsMatch(review),
                "The Review tab shows no Evergreen WebView2 download URL when the runtime is "
                    + "missing. It showed:" + Environment.NewLine + review);
            Assert.Contains(RunRoot, review);

            // The sentence names the tabs the engineer is actually looking at. "The Actions
            // tab still works" was a pointer to a tab that no longer exists under that name.
            Assert.Contains("Review, Ask and Model check tabs cannot be shown", review);
            Assert.Contains("The Extract tab still works.", review);
        });
    }

    /// <summary>
    /// The fourth tab (T083) is created on first activation rather than at add-in load, so its
    /// failure arrives later than the other two - and it must arrive as the same panel.
    ///
    /// Both halves are asserted here because they are one behaviour seen twice. Before the tab
    /// is opened it holds its placeholder and has asked WebView2 for nothing; after it is
    /// opened it holds the documented fallback, with the download URL and the run root in plain
    /// text, and the Extract tab is still doing its three jobs.
    /// </summary>
    [Fact]
    public void TheModelCheckTabIsLoadedOnFirstActivationAndFailsIntoTheSameFallback()
    {
        WithPane(async (control, factory) =>
        {
            TabPage tab = TabNamed(control, "Model check");

            string before = TextOf(tab);
            Assert.False(
                EvergreenDownload.IsMatch(before),
                "The Model check tab loaded its page at add-in load; it is created on first "
                    + "activation (T083). It showed:" + Environment.NewLine + before);
            Assert.Contains(TaskPaneControl.ModelCheckPending, before);

            Exception? escaped = await Record.ExceptionAsync(() => control.ActivateModelCheckAsync());
            Assert.True(
                escaped == null,
                "Opening the Model check tab with no WebView2 runtime threw: " + escaped);

            string after = TextOf(tab);
            Assert.True(
                EvergreenDownload.IsMatch(after),
                "The Model check tab shows no Evergreen WebView2 download URL when the runtime "
                    + "is missing. It showed:" + Environment.NewLine + after);
            Assert.Contains(RunRoot, after);
            Assert.Contains("Review, Ask and Model check tabs cannot be shown", after);

            // Still one environment: the fourth tab shares the cached failure rather than
            // asking the factory again on every activation.
            Assert.Equal(1, factory.Calls);
            await control.ActivateModelCheckAsync();
            Assert.Equal(1, factory.Calls);

            Assert.True(
                Descendants(TabNamed(control, "Extract")).OfType<Button>().Any(
                    button => button.Text == "Extract evidence" && button.Enabled),
                "The Extract tab stopped working when the Model check tab failed.");
        });
    }

    /// <summary>
    /// T120: the fifth tab (feature 004) is created on first activation too, and for a harder
    /// reason than tab 4's. Five tabs loaded at add-in load would cost <b>four</b> renderer
    /// processes inside the SOLIDWORKS process before the engineer has pressed anything
    /// (RK-11); two of the five are now lazy, so a session that never opens either pays for
    /// neither.
    /// </summary>
    [Fact]
    public void TheRemodelTabIsLoadedOnFirstActivationAndFailsIntoTheSameFallback()
    {
        WithPane(async (control, factory) =>
        {
            TabPage tab = TabNamed(control, "Remodel");

            string before = TextOf(tab);
            Assert.False(
                EvergreenDownload.IsMatch(before),
                "The Remodel tab loaded its page at add-in load; it is created on first "
                    + "activation (T121). It showed:" + Environment.NewLine + before);
            Assert.Contains(TaskPaneControl.RemodelPending, before);

            Exception? escaped = await Record.ExceptionAsync(() => control.ActivateRemodelAsync());
            Assert.True(
                escaped == null,
                "Opening the Remodel tab with no WebView2 runtime threw: " + escaped);

            string after = TextOf(tab);
            Assert.True(
                EvergreenDownload.IsMatch(after),
                "The Remodel tab shows no Evergreen WebView2 download URL when the runtime is "
                    + "missing. It showed:" + Environment.NewLine + after);
            Assert.Contains(RunRoot, after);

            // The fallback message is the one the other tabs already render, word for word: a
            // second sentence about the same missing runtime would be a second thing to keep
            // in step with the download URL.
            Assert.Contains("Review, Ask and Model check tabs cannot be shown", after);
            Assert.Contains("The Extract tab still works.", after);
        });
    }

    /// <summary>
    /// T080: the sixth tab (feature 006) is created on first activation too, and for the reason
    /// tabs 4 and 5 are. Six tabs loaded at add-in load would cost <b>five</b> renderer
    /// processes inside the SOLIDWORKS process before the engineer has pressed anything; three
    /// of the six are lazy, so a session that opens none of them pays for none of them.
    ///
    /// The Standards tab is the one most likely to be opened on a release day and never
    /// otherwise, which is exactly the shape laziness is for.
    /// </summary>
    [Fact]
    public void TheStandardsTabIsLoadedOnFirstActivationAndFailsIntoTheSameFallback()
    {
        WithPane(async (control, factory) =>
        {
            TabPage tab = TabNamed(control, "Standards");

            string before = TextOf(tab);
            Assert.False(
                EvergreenDownload.IsMatch(before),
                "The Standards tab loaded its page at add-in load; it is created on first "
                    + "activation (T081). It showed:" + Environment.NewLine + before);
            Assert.Contains(TaskPaneControl.StandardsPending, before);

            Exception? escaped = await Record.ExceptionAsync(() => control.ActivateStandardsAsync());
            Assert.True(
                escaped == null,
                "Opening the Standards tab with no WebView2 runtime threw: " + escaped);

            string after = TextOf(tab);
            Assert.True(
                EvergreenDownload.IsMatch(after),
                "The Standards tab shows no Evergreen WebView2 download URL when the runtime is "
                    + "missing. It showed:" + Environment.NewLine + after);
            Assert.Contains(RunRoot, after);

            // The fallback message is the one every other tab already renders, word for word.
            Assert.Contains("Review, Ask and Model check tabs cannot be shown", after);
            Assert.Contains("The Extract tab still works.", after);

            // Still one environment, shared with the five tabs that came before it.
            Assert.Equal(1, factory.Calls);
        });
    }

    [Fact]
    public void ActivatingTheStandardsTabTwiceLoadsItOnce()
    {
        WithPane(async (control, factory) =>
        {
            Task first = control.ActivateStandardsAsync();
            await first;

            Task second = control.ActivateStandardsAsync();
            Assert.Same(first, second);
            await second;

            Assert.Equal(1, factory.Calls);
        });
    }

    /// <summary>
    /// Activating twice creates one WebView. The activation task is cached - failure included -
    /// so the second selection of the tab is not a second page load, and the count of
    /// environment requests stays at one.
    /// </summary>
    [Fact]
    public void ActivatingTheRemodelTabTwiceLoadsItOnce()
    {
        WithPane(async (control, factory) =>
        {
            Task first = control.ActivateRemodelAsync();
            await first;

            Task second = control.ActivateRemodelAsync();
            Assert.Same(first, second);
            await second;

            Assert.Equal(1, factory.Calls);
        });
    }

    /// <summary>
    /// The three lazy tabs share the one environment with the two eager ones. Opening all three
    /// is still one `CreateAsync`, which is the rule that matters: a second environment over the
    /// same user data folder fails at runtime.
    /// </summary>
    [Fact]
    public void OpeningEveryLazyTabStillAsksForOneEnvironment()
    {
        WithPane(async (control, factory) =>
        {
            await control.ActivateModelCheckAsync();
            await control.ActivateRemodelAsync();
            await control.ActivateStandardsAsync();

            Assert.Equal(1, factory.Calls);
            Assert.Same(control.EnvironmentAsync(), control.EnvironmentAsync());
        });
    }

    /// <summary>
    /// The order the engineer reads left to right, and the order the three contracts name:
    /// Review, Ask, Extract, Model check, Remodel, Standards (T080, FR-035).
    /// </summary>
    [Fact]
    public void TheSixTabsAreInTheOrderTheContractsName()
    {
        WithPane((control, factory) =>
        {
            string[] captions = Descendants(control)
                .OfType<TabPage>()
                .Select(tab => tab.Text)
                .ToArray();

            Assert.Equal(
                new[] { "Review", "Extract", "Model check", "Remodel", "Standards" },
                captions);
        });
    }

    [Fact]
    public void AMissingRuntimeLeavesTheExtractTabWorking()
    {
        WithPane((control, factory) =>
        {
            List<Button> buttons = Descendants(TabNamed(control, "Extract"))
                .OfType<Button>()
                .ToList();

            foreach (string caption in new[] { "Extract evidence", "Interference", "Capture selection" })
            {
                Button? button = buttons.FirstOrDefault(
                    candidate => string.Equals(candidate.Text, caption, StringComparison.Ordinal));

                Assert.True(button != null, $"The Extract tab has no \"{caption}\" button.");
                Assert.True(button!.Enabled, $"\"{caption}\" is disabled because WebView2 is missing.");
            }
        });
    }

    /// <summary>
    /// The reuse rule, with a factory that succeeds: a second caller - the Terminal tab when
    /// T060 gives it one, and any caller after it - is handed the environment the first caller
    /// got, not a second one over the same user data folder.
    ///
    /// The count alone cannot say this. Only <c>InitializeAsync</c> asks for an environment
    /// today and the Terminal tab is still a placeholder, so a pane that caches nothing would
    /// also report one call; what distinguishes caching from not caching is asking twice and
    /// getting the same object back. The factory therefore hands out a <b>fresh</b> task every
    /// time it is called, so reference equality is evidence rather than an artefact of
    /// <c>Task.FromResult</c>.
    ///
    /// The environment in the task is null. Nothing here dereferences it - the question is
    /// which task <see cref="TaskPaneControl.EnvironmentAsync"/> returns - and a real
    /// <see cref="CoreWebView2Environment"/> would need the Evergreen runtime, a browser
    /// process and a user data folder to answer a question about a field assignment.
    /// </summary>
    [Fact]
    public void ASecondCallerIsHandedTheEnvironmentTheFirstOneGot()
    {
        var factory = new SucceedingEnvironmentFactory();

        StaHost.Run(form =>
        {
            using (var control = new TaskPaneControl(new TaskPaneOptions(factory, RunRoot)))
            {
                form.Controls.Add(control);

                Task<CoreWebView2Environment> first = control.EnvironmentAsync();
                Task<CoreWebView2Environment> second = control.EnvironmentAsync();

                Assert.Same(first, second);
                Assert.Equal(1, factory.Calls);
            }

            return Task.CompletedTask;
        });
    }

    [Fact]
    public void TheEnvironmentIsAskedForOnceHoweverManyTabsNeedIt()
    {
        WithPane((control, factory) =>
        {
            // Both WebView2 tabs exist and both are meant to share one environment, so one
            // failed attempt is the whole story: two would mean two environments on a machine
            // where the runtime is present, over the same user data folder.
            Assert.NotNull(TabNamed(control, "Review"));
            // Ask is hidden (TaskPaneControl.AskTabShown), so it neither exists nor asks.
            Assert.DoesNotContain("Ask", Descendants(control).OfType<TabPage>().Select(tab => tab.Text));
            Assert.NotNull(TabNamed(control, "Model check"));
            Assert.NotNull(TabNamed(control, "Remodel"));
            Assert.NotNull(TabNamed(control, "Standards"));
            Assert.Equal(1, factory.Calls);

            // The failure is cached like a success: a workstation with no runtime must not
            // retry the create on every caller, and the cached faulted task is what makes the
            // count above mean "once per process" rather than "once so far".
            Assert.Same(control.EnvironmentAsync(), control.EnvironmentAsync());
            Assert.Equal(1, factory.Calls);
        });
    }

    [Fact]
    public void TheRealFactoryUsesItsOwnWritableUserDataFolderUnderLocalAppData()
    {
        string expectedRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "SwReview",
            "WebView2");

        string folder = WebViewEnvironmentFactory.UserDataFolder;

        Assert.StartsWith(expectedRoot + Path.DirectorySeparatorChar, folder, StringComparison.OrdinalIgnoreCase);
        Assert.True(
            folder.Length > expectedRoot.Length + 1,
            $"{folder} has no per-instance segment under {expectedRoot}.");
    }

    // ---- the pane, with a runtime that is not there ------------------------------------------

    /// <summary>
    /// Builds the pane on an STA thread with a factory that fails the way a workstation without
    /// the runtime fails, initializes it, and asserts that nothing escaped.
    /// </summary>
    private static void WithPane(Action<TaskPaneControl, CountingEnvironmentFactory> assertions) =>
        WithPane((control, factory) =>
        {
            assertions(control, factory);
            return Task.CompletedTask;
        });

    /// <summary>
    /// The same pane for a body that has to await something - opening the Model check tab,
    /// which is loaded on first activation rather than at add-in load (T083).
    /// </summary>
    private static void WithPane(Func<TaskPaneControl, CountingEnvironmentFactory, Task> assertions)
    {
        var factory = new CountingEnvironmentFactory();

        StaHost.Run(async form =>
        {
            using (var control = new TaskPaneControl(new TaskPaneOptions(factory, RunRoot)))
            {
                control.Dock = DockStyle.Fill;
                form.Controls.Add(control);

                Exception? escaped = await Record.ExceptionAsync(() => control.InitializeAsync());

                Assert.True(
                    escaped == null,
                    "A missing WebView2 runtime reached SOLIDWORKS as an exception: " + escaped);

                // Not the "exactly once" assertion, which is its own test below - only that the
                // pane really did try, so a pane that quietly skips WebView2 cannot pass the
                // fallback assertions by never reaching the failure they describe.
                Assert.True(factory.Calls >= 1, "The pane never asked for a WebView2 environment.");

                await assertions(control, factory);
            }
        });
    }

    /// <summary>
    /// A factory that succeeds, handing back a distinct task object on every call so that
    /// "the same task came back" cannot be true by accident.
    /// </summary>
    private sealed class SucceedingEnvironmentFactory : IWebViewEnvironmentFactory
    {
        private int _calls;

        public int Calls => Volatile.Read(ref _calls);

        public Task<CoreWebView2Environment> CreateAsync()
        {
            Interlocked.Increment(ref _calls);
            var completion = new TaskCompletionSource<CoreWebView2Environment>();
            completion.SetResult(null!);
            return completion.Task;
        }
    }

    /// <summary>
    /// What `CoreWebView2Environment.CreateAsync` throws when the Evergreen runtime is not
    /// installed, plus a count, because "created once per process" is only observable as a count.
    /// </summary>
    private sealed class CountingEnvironmentFactory : IWebViewEnvironmentFactory
    {
        private int _calls;

        public int Calls => Volatile.Read(ref _calls);

        public Task<CoreWebView2Environment> CreateAsync()
        {
            Interlocked.Increment(ref _calls);
            throw new WebView2RuntimeNotFoundException(
                "Couldn't find Microsoft Edge WebView2 Runtime (simulated by WebViewFallbackTests).");
        }
    }

    // ---- reading the control ------------------------------------------------------------------

    private static TabPage TabNamed(Control root, string caption)
    {
        TabPage? page = Descendants(root)
            .OfType<TabPage>()
            .FirstOrDefault(candidate => string.Equals(candidate.Text, caption, StringComparison.Ordinal));

        Assert.True(
            page != null,
            $"The Task Pane has no \"{caption}\" tab; it has: "
                + string.Join(", ", Descendants(root).OfType<TabPage>().Select(tab => tab.Text)));
        return page!;
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
}
