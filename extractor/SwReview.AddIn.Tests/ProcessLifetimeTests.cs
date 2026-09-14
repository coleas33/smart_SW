using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;
using SwReview.AddIn.Terminal;
using SwReview.AddIn.ToolService;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T050: nothing the pane starts outlives the pane.
///
/// The backend holds a loopback port and, in a real run, a provider key in its environment;
/// a CLI under ConPTY holds a console. If SOLIDWORKS crashes - or the add-in is unloaded
/// without running its cleanup - neither may be left behind. A Windows job object with
/// `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is the only mechanism that survives the parent dying
/// without warning, because the kernel closes the handle for us.
///
/// The ordering is the part that is easy to get wrong and impossible to notice: a child
/// assigned to the job *after* it has started running has already had a window in which it
/// could exit, spawn, or (for a fast-exiting child) escape the job entirely. So the child is
/// created with `CREATE_SUSPENDED`, assigned, and only then resumed. The test for that is the
/// marker file: while the process is suspended the stub has provably executed no instruction,
/// so the marker cannot exist yet, and it appears only after <see cref="ChildProcess.Resume"/>.
///
/// Scope: both children are proved here against real processes - the backend, and (since T053)
/// the ConPTY child, which takes a different branch of <see cref="ChildProcess.StartSuspended"/>
/// and so is worth its own case. The pipe-name half is proved against <see cref="PipeNames"/>,
/// the generator the in-process tool service (T047) names its pipe with.
/// </summary>
public sealed class ProcessLifetimeTests
{
    /// <summary>Shared with <see cref="BackendProcessTests"/>: a PID that is gone answers false
    /// rather than throwing, which is what every assertion here actually wants to know.</summary>
    public static bool IsRunning(int processId)
    {
        try
        {
            using (Process process = Process.GetProcessById(processId))
            {
                return !process.HasExited;
            }
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    [Fact]
    public void AChildIsInsideTheJobBeforeItsFirstThreadRuns()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.RecordsThatItRan().PrintsHandshake();

            using (ChildProcess child = ChildProcess.StartSuspended(StartInfo(stub), job))
            {
                // The child exists and is ours, and it is in the job...
                Assert.True(child.ProcessId > 0);
                Assert.True(job.Contains(child.ProcessId));

                // ...but has run no code at all: its initial thread is still suspended. The
                // wait is comfortably longer than the child's start-up, so a build that
                // assigned the job after resuming would be caught here rather than passing by
                // being quicker than the child.
                Thread.Sleep(1500);
                Assert.False(File.Exists(stub.MarkerPath));
                Assert.False(child.HasExited);

                child.Resume();

                Assert.True(StubBackend.Waits(() => File.Exists(stub.MarkerPath)));
            }
        }
    }

    [Fact]
    public void ClosingTheJobKillsTheChildEvenWithoutAGracefulStop()
    {
        using (var stub = new StubBackend())
        {
            stub.RecordsThatItRan().PrintsHandshake();

            // The child is deliberately never disposed and never killed, and it is not in a
            // `using`: ChildProcess.Dispose() calls Kill(), so a child inside one would be
            // terminated by us and this test would pass against a job built without
            // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. Closing the job has to be the only thing
            // that happens, because that is the whole SOLIDWORKS-crash path: nothing of ours
            // runs, the kernel closes the handle, and the kernel kills the child.
            //
            // The two handles the ChildProcess holds leak for the life of the test run. That
            // is the price of proving the mechanism; there is no other way to reach the state
            // the crash leaves behind from inside a process that is still alive.
            var job = new JobObject();
            ChildProcess child = ChildProcess.StartSuspended(StartInfo(stub), job);
            child.Resume();
            int processId = child.ProcessId;
            Assert.True(StubBackend.Waits(() => File.Exists(stub.MarkerPath)));
            Assert.True(IsRunning(processId));

            job.Dispose();

            Assert.True(StubBackend.Waits(() => !IsRunning(processId)));
            GC.KeepAlive(child);
        }
    }

    [Fact]
    public void DisposingTheHostEndsTheBackend()
    {
        using (var stub = new StubBackend())
        {
            stub.PrintsHandshake(port: 41001);
            int processId;

            using (var job = new JobObject())
            using (BackendProcess backend = BackendProcess.Start(Options(stub, job)))
            {
                processId = backend.ProcessId;
                Assert.True(job.Contains(processId));
            }

            Assert.True(StubBackend.Waits(() => !IsRunning(processId)));
        }
    }

    [Fact]
    public void TwoBackendsInOneProcessKeepDistinctPortsTokensAndProcesses()
    {
        using (var first = new StubBackend())
        using (var second = new StubBackend())
        using (var job = new JobObject())
        {
            first.PrintsHandshake(port: 41101, token: "first-" + StubBackend.DefaultToken);
            second.PrintsHandshake(port: 41102, token: "second-" + StubBackend.DefaultToken);
            int firstPid;
            int secondPid;

            using (BackendProcess a = BackendProcess.Start(Options(first, job)))
            using (BackendProcess b = BackendProcess.Start(Options(second, job)))
            {
                firstPid = a.ProcessId;
                secondPid = b.ProcessId;

                Assert.NotEqual(a.Port, b.Port);
                Assert.NotEqual(a.Token, b.Token);
                Assert.NotEqual(a.ProcessId, b.ProcessId);
                Assert.True(job.Contains(firstPid));
                Assert.True(job.Contains(secondPid));
            }

            Assert.True(StubBackend.Waits(() => !IsRunning(firstPid) && !IsRunning(secondPid)));
        }
    }

    [Fact]
    public void AChildThatExitsWhileSuspendedCannotEscapeTheJob()
    {
        // The reason the ordering is written down: a child that runs to completion faster than
        // the parent can call AssignProcessToJobObject would never have been in the job at all.
        // Started suspended, even an instant-exit child is inside it before it can run.
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.ExitsWith(0);

            using (ChildProcess child = ChildProcess.StartSuspended(StartInfo(stub), job))
            {
                Assert.True(job.Contains(child.ProcessId));

                child.Resume();
                Assert.True(child.WaitForExit(20000));
                Assert.Equal(0, child.ExitCode);
            }
        }
    }

    // ---- two hosts in one process -------------------------------------------------------

    [Fact]
    public void TwoHostsInOneProcessGetDistinctPipeNames()
    {
        // Two Task Panes in one SOLIDWORKS - two documents, or a pane reopened after a
        // reload - are two hosts in one process. A fixed pipe name would make the second
        // host's server fail to listen (or, worse, make the second host's page talk to the
        // first host's SOLIDWORKS scope), so the name is generated per host and never
        // derived from anything the two share.
        var names = new HashSet<string>(StringComparer.Ordinal);
        for (int index = 0; index < 100; index++)
        {
            Assert.True(names.Add(PipeNames.NewToolServiceName()));
        }
    }

    [Fact]
    public void AToolServicePipeNameIsTheContractsShape()
    {
        // `swreview-<guid>` (T047). The shape is asserted rather than assumed because the
        // name is half of what the page and the backend are told to connect to, and a name
        // with a path separator or a space in it is a connection failure at the far end.
        string name = PipeNames.NewToolServiceName();

        Assert.StartsWith("swreview-", name, StringComparison.Ordinal);
        Assert.Equal(32, name.Substring("swreview-".Length).Length);
        Assert.True(Guid.TryParseExact(name.Substring("swreview-".Length), "N", out _));
        Assert.DoesNotContain(@"\", name, StringComparison.Ordinal);
        Assert.DoesNotContain(" ", name, StringComparison.Ordinal);
    }

    /// <summary>
    /// The same proof as <see cref="AChildIsInsideTheJobBeforeItsFirstThreadRuns"/>, for the
    /// child T053 added: the one attached to a pseudo-console.
    ///
    /// It is worth making twice because the two children are created down different branches of
    /// <see cref="ChildProcess.StartSuspended"/> - a pseudo-console child takes the
    /// `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE` attribute, no pipes, no handle list and neither
    /// console creation flag - and the job assignment sits after that branch for both. A change
    /// that moved the assignment into the non-pty side would leave the CLI, which is the child
    /// holding a console and the tool-service secret's neighbourhood, outside the job.
    ///
    /// The marker file is the proof that "suspended" means what it says: while the initial
    /// thread is suspended the child has provably executed no instruction, so `marker.txt`
    /// cannot exist yet, and it appears only after <see cref="ChildProcess.Resume"/>.
    /// </summary>
    [Fact]
    public void AConPtyChildIsInsideTheJobBeforeItsFirstThreadRuns()
    {
        string folder = Path.Combine(
            Path.GetTempPath(), "SwReview.ConPty.Job", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        string marker = Path.Combine(folder, "marker.txt");

        try
        {
            using (var conpty = ConPty.Create(80, 25))
            using (var job = new JobObject())
            {
                // No space anywhere in the argument, so `cmd.exe` re-parses exactly what it was
                // given: `echo>marker.txt` writes a line into the run folder and exits.
                var info = new ChildProcessStartInfo(Cmd, new[] { "/c", "echo>marker.txt" })
                {
                    WorkingDirectory = folder,
                    PseudoConsole = conpty.Handle,
                };

                using (ChildProcess child = ChildProcess.StartSuspended(info, job))
                {
                    Assert.True(child.ProcessId > 0);
                    Assert.True(job.Contains(child.ProcessId));

                    // `ClosePseudoConsole` flushes what the child drew before it returns, so
                    // something has to be reading the console or the dispose below can block.
                    // In the real session that is TerminalSession's read loop.
                    Thread drain = Drain(conpty);

                    Thread.Sleep(1500);
                    Assert.False(File.Exists(marker));
                    Assert.False(child.HasExited);

                    child.Resume();

                    Assert.True(StubBackend.Waits(() => File.Exists(marker)));
                    Assert.True(child.WaitForExit(20000));
                    drain.Join(2000);
                }
            }
        }
        finally
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
    }

    private static string Cmd => Path.Combine(Environment.SystemDirectory, "cmd.exe");

    private static Thread Drain(ConPty conpty)
    {
        var thread = new Thread(() =>
        {
            var buffer = new byte[4096];
            try
            {
                while (conpty.Output.Read(buffer, 0, buffer.Length) > 0)
                {
                }
            }
            catch (IOException)
            {
            }
            catch (ObjectDisposedException)
            {
            }
        })
        {
            IsBackground = true,
            Name = "conpty-job-test-drain",
        };
        thread.Start();
        return thread;
    }

    private static ChildProcessStartInfo StartInfo(StubBackend stub)
    {
        var info = new ChildProcessStartInfo(stub.Command.Executable, stub.Command.Arguments)
        {
            WorkingDirectory = stub.RunRoot,
        };

        foreach (KeyValuePair<string, string> knob in stub.Knobs)
        {
            info.Environment[knob.Key] = knob.Value;
        }

        return info;
    }

    private static BackendStartOptions Options(StubBackend stub, JobObject job)
    {
        var options = new BackendStartOptions(stub.Command, stub.LogPath)
        {
            RunRoot = stub.RunRoot,
            AllowOrigin = "https://swreview.invalid",
            Job = job,
            // The stub does not handle the shutdown request, and none of these tests is about
            // the grace period; waiting out the production five seconds per child would make
            // this file the slowest in the suite for no assertion.
            StopGrace = TimeSpan.FromMilliseconds(500),
            HealthProbe = (origin, token) => true,
        };

        foreach (KeyValuePair<string, string> knob in stub.Knobs)
        {
            options.Environment[knob.Key] = knob.Value;
        }

        return options;
    }
}
