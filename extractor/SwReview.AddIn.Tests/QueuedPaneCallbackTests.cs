using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
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

    /// <summary>
    /// The reviews of owner decision 157A: what a check host queues behind the pane's posts runs on the pane's thread,
    /// after what was queued there before it - so a run's minute starts once its reply has been delivered - and never
    /// on the caller's thread while the pane can queue it.
    /// </summary>
    [Fact]
    public void WhatIsQueuedBehindThePostsRunsOnThePanesThreadAfterThem()
    {
        StaHost.Run(async form =>
        {
            using (var pane = Pane())
            {
                form.Controls.Add(pane);
                Assert.NotEqual(IntPtr.Zero, pane.Handle);
                int paneThread = Thread.CurrentThread.ManagedThreadId;
                var order = new List<string>();
                var ran = new TaskCompletionSource<int>();
                await Task.Run(() =>
                {
                    pane.BeginInvoke(new Action(() => order.Add("posted before")));
                    pane.AfterPosts(() =>
                    {
                        order.Add("behind the posts");
                        ran.SetResult(Thread.CurrentThread.ManagedThreadId);
                    });
                });

                Assert.Equal(paneThread, await ran.Task);
                Assert.Equal(new[] { "posted before", "behind the posts" }, order);
            }
        });
    }

    /// <summary>
    /// A pane that cannot queue - closed - runs what is queued behind its posts at once, so a check's minute is never
    /// left waiting for a delivery that will not come; and a failure inside it stays inside it.
    /// </summary>
    [Fact]
    public void AClosedPaneRunsWhatIsQueuedBehindItsPostsAtOnce()
    {
        StaHost.Run(form =>
        {
            var pane = Pane();
            form.Controls.Add(pane);
            pane.Dispose();
            int runs = 0;

            pane.AfterPosts(() => runs++);
            pane.AfterPosts(() => throw new InvalidOperationException("FICT the minute's mark failed"));

            Assert.Equal(1, runs);
            return Task.CompletedTask;
        });
    }

    /// <summary>
    /// A failure inside what is queued behind the posts stays inside it: SOLIDWORKS' thread carries on with the work
    /// queued after it.
    /// </summary>
    [Fact]
    public void AFailureBehindThePostsStaysInsideIt()
    {
        StaHost.Run(async form =>
        {
            using (var pane = Pane())
            {
                form.Controls.Add(pane);
                Assert.NotEqual(IntPtr.Zero, pane.Handle);
                var after = new TaskCompletionSource<bool>();
                await Task.Run(() =>
                {
                    pane.AfterPosts(() => throw new InvalidOperationException("FICT the minute's mark failed"));
                    pane.BeginInvoke(new Action(() => after.SetResult(true)));
                });

                Assert.True(await after.Task);
            }
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
