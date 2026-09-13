using System;
using System.Runtime.ExceptionServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Runs a test body on a dedicated STA thread with a WinForms message loop and one hidden
/// form, and rethrows whatever the body threw on the calling thread.
///
/// Both WebView2 tests need this and neither can do without it. `CoreWebView2Controller` needs
/// a window handle and a pumping message loop - its async completions are posted to the
/// creating thread's <see cref="WindowsFormsSynchronizationContext"/>, so awaiting
/// `EnsureCoreWebView2Async` on a thread with no loop deadlocks - and the Task Pane control is
/// a WinForms `UserControl`, which is only honest to exercise on the kind of thread SOLIDWORKS
/// gives it: a single-threaded apartment. xUnit's own threads are MTA, so the tests borrow one
/// of their own.
///
/// The form is created invisible (`Opacity = 0`) rather than minimized: a minimized window has
/// no usable client area, and WebView2 will not lay a page out inside one.
/// </summary>
internal static class StaHost
{
    /// <summary>The ceiling for one body; a WebView2 boot on a cold machine is a few seconds.</summary>
    public static readonly TimeSpan DefaultTimeout = TimeSpan.FromSeconds(90);

    public static void Run(Func<Form, Task> body) => Run(body, DefaultTimeout);

    public static void Run(Func<Form, Task> body, TimeSpan timeout)
    {
        if (body == null)
        {
            throw new ArgumentNullException(nameof(body));
        }

        Exception? failure = null;

        var thread = new Thread(() =>
        {
            var form = new Form
            {
                Width = 900,
                Height = 700,
                ShowInTaskbar = false,
                Opacity = 0,
                Text = "SwReview tests",
            };

            // Load rather than the constructor: the handle exists by then, which is what
            // WebView2 and every Invoke inside the body need.
            form.Load += async (sender, args) =>
            {
                try
                {
                    await body(form);
                }
                catch (Exception error)
                {
                    failure = error;
                }
                finally
                {
                    form.Close();
                }
            };

            try
            {
                Application.Run(form);
            }
            catch (Exception error)
            {
                failure ??= error;
            }
            finally
            {
                form.Dispose();
            }
        });

        thread.SetApartmentState(ApartmentState.STA);
        thread.IsBackground = true;
        thread.Start();

        if (!thread.Join(timeout))
        {
            throw new TimeoutException(
                $"The STA test body did not finish within {timeout.TotalSeconds:0} seconds.");
        }

        if (failure != null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }
}
