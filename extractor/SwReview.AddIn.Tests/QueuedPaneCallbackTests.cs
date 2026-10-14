using System;
using System.Reflection;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// An async WinForms post returns before its delegate executes, so the posting caller's catch
/// cannot contain a later callback failure. Exercise the queued delegate targets on an STA
/// with a test-owned outer catch, so a regression fails the test instead of crashing the host.
/// No WebView2 environment or SOLIDWORKS is initialized.
/// </summary>
public sealed class QueuedPaneCallbackTests
{
    [Fact]
    public void QueuedPostContainsAViewSelectorThatFailsAfterScheduling()
    {
        StaHost.Run(async form =>
        {
            using (var pane = Pane())
            {
                form.Controls.Add(pane);
                int selections = 0;
                Func<WebView2?> selector = () =>
                {
                    selections++;
                    throw new ObjectDisposedException("fictional view");
                };

                Assert.Null(await Queued(form, pane, "PostOnUiThread", selector, "{}"));
                Assert.Equal(1, selections);
            }
        });
    }

    [Fact]
    public void QueuedRefreshContainsASessionReaderThatFailsAfterScheduling()
    {
        StaHost.Run(async form =>
        {
            var options = Options();
            using (var pane = new TaskPaneControl(options))
            {
                form.Controls.Add(pane);
                int reads = 0;
                options.CurrentSessionRunDirectory = () =>
                {
                    reads++;
                    throw new InvalidOperationException("fictional session closed");
                };

                Assert.Null(await Queued(form, pane, "RefreshOnUiThread"));
                Assert.Equal(1, reads);

                // A refused refresh does not poison subsequent UI work.
                options.CurrentSessionRunDirectory = () => null;
                Assert.Null(await Queued(form, pane, "RefreshOnUiThread"));
            }
        });
    }

    [Fact]
    public void AQueuedRefreshAfterDisposalReadsNoDocumentOrSession()
    {
        StaHost.Run(async form =>
        {
            var options = Options();
            var pane = new TaskPaneControl(options);
            form.Controls.Add(pane);
            int reads = 0;
            options.DocumentPresent = () => { reads++; return true; };
            options.EvidencePresent = () => { reads++; return true; };
            options.CurrentSessionRunDirectory = () => { reads++; return null; };
            pane.Dispose();

            Assert.Null(await Queued(form, pane, "RefreshOnUiThread"));
            Assert.Equal(0, reads);
        });
    }

    [Fact]
    public void AQueuedPostAfterDisposalDoesNotSelectTheClosedView()
    {
        StaHost.Run(async form =>
        {
            var pane = Pane();
            form.Controls.Add(pane);
            int selections = 0;
            Func<WebView2?> selector = () => { selections++; return null; };
            pane.Dispose();

            Assert.Null(await Queued(form, pane, "PostOnUiThread", selector, "{}"));
            Assert.Equal(0, selections);
        });
    }

    private static TaskPaneControl Pane() => new TaskPaneControl(Options());

    private static TaskPaneOptions Options() =>
        new TaskPaneOptions(new UnusedEnvironmentFactory(), @"C:\FICT\review-runs");

    private static Task<Exception?> Queued(
        System.Windows.Forms.Control queue, TaskPaneControl pane, string target, params object[] arguments)
    {
        MethodInfo method = typeof(TaskPaneControl).GetMethod(
            target, BindingFlags.Instance | BindingFlags.NonPublic)!;
        Assert.NotNull(method);
        var done = new TaskCompletionSource<Exception?>();
        queue.BeginInvoke(new Action(() =>
        {
            Exception? failure = Record.Exception(() => method.Invoke(pane, arguments));
            done.SetResult(failure is TargetInvocationException wrapped ? wrapped.InnerException : failure);
        }));
        return done.Task;
    }

    private sealed class UnusedEnvironmentFactory : IWebViewEnvironmentFactory
    {
        public Task<CoreWebView2Environment> CreateAsync() =>
            throw new InvalidOperationException("These callback tests never initialize WebView2.");
    }
}
