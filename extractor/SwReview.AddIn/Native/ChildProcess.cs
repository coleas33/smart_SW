using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace SwReview.AddIn.Native;

/// <summary>What to start, where, and with which environment.</summary>
public sealed class ChildProcessStartInfo
{
    public ChildProcessStartInfo(string executable, IEnumerable<string> arguments)
    {
        if (string.IsNullOrWhiteSpace(executable))
        {
            throw new ArgumentException("an executable path is required", nameof(executable));
        }

        Executable = executable;
        Arguments = (arguments ?? Enumerable.Empty<string>()).ToList();
    }

    public string Executable { get; }

    /// <summary>Arguments as separate strings; quoting for the command line is done here, so a
    /// caller never has to get Windows' backslash-before-quote rule right.</summary>
    public IReadOnlyList<string> Arguments { get; }

    public string? WorkingDirectory { get; set; }

    /// <summary>Variables added to (or replacing) the parent's environment. This is the only
    /// channel a provider key travels on (FR-015).</summary>
    public IDictionary<string, string> Environment { get; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// The `HPCON` of a pseudo-console to give the child instead of pipes (`SwReview.AddIn.
    /// Terminal.ConPty.Handle`). Zero - the default - starts the child the ordinary way.
    ///
    /// A pseudo-console child differs in four ways, all of them forced by
    /// `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`, and all of them handled by
    /// <see cref="ChildProcess.StartSuspended"/> rather than left to the caller: its standard
    /// handles have to be *refused* rather than supplied, so that the console driver hands it
    /// the console's own (see the comment on that branch - this is the part that silently
    /// produces an empty terminal when it is left out), and no pipes are made, so
    /// <see cref="ChildProcess.StandardOutput"/> and <see cref="ChildProcess.StandardError"/>
    /// are empty; nothing is inherited, because the console is passed as an attribute rather
    /// than as a handle; `CREATE_NO_WINDOW` is pointless, because the console it would suppress
    /// is the pseudo-console; and `CREATE_NEW_PROCESS_GROUP` is actively wrong, because it
    /// starts the child with Ctrl+C disabled and Ctrl+C is a key the engineer will press.
    /// </summary>
    public IntPtr PseudoConsole { get; set; }

    /// <summary>
    /// Whether the child's standard input is a pipe this process writes to
    /// (<see cref="ChildProcess.StandardInput"/>) instead of `NUL`.
    ///
    /// Off by default, and deliberately: every other child the pane starts is spoken to through
    /// a console or a pipe server, and a child holding an open stdin pipe it never reads is a
    /// child that cannot be ended by closing it. The one caller that needs it is the Codex
    /// app-server listing probe (T062), which is a JSON-RPC conversation on stdio and has no
    /// other way in. Ignored for a pseudo-console child, whose input is the console's.
    /// </summary>
    public bool RedirectStandardInput { get; set; }
}

/// <summary>
/// A child process created suspended, so it can be put in a <see cref="JobObject"/> before it
/// runs a single instruction, with stdout and stderr on pipes and stdin on `NUL`.
///
/// `System.Diagnostics.Process` cannot do this: it has no `CREATE_SUSPENDED`, so anything it
/// starts is already running by the time a job assignment could happen. For a backend that
/// binds a loopback port and holds a key in its environment that window is exactly the one
/// that leaves an orphan behind when SOLIDWORKS crashes during start-up.
///
/// Two further reasons this is hand-rolled rather than borrowed:
///
/// <b>Handle inheritance is restricted to our three pipe handles</b> with
/// `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`. `bInheritHandles = TRUE` on its own hands the child
/// *every* inheritable handle in the process - and the process here is SLDWORKS.exe, full of
/// other add-ins' files and sockets. A long-lived Python child holding one of those open is a
/// leak nobody would ever trace back to us.
///
/// <b>The environment block is built explicitly</b> so the key is placed in it and nowhere
/// else, and so variables can be removed rather than only added.
///
/// <b>The child is its own process group on a console we can reach</b>
/// (`CREATE_NEW_PROCESS_GROUP`), which is what makes <see cref="TryRequestStop"/> possible.
/// Without it the only way to end the child is `TerminateProcess`, which delivers no signal,
/// so the backend's own shutdown - the one that gives every live chat an ended time - could
/// never run.
/// </summary>
public sealed class ChildProcess : IDisposable
{
    private const uint CreateSuspended = 0x00000004;
    private const uint CreateNoWindow = 0x08000000;
    private const uint CreateNewProcessGroup = 0x00000200;
    private const uint CtrlBreakEvent = 1;
    private const uint CreateUnicodeEnvironment = 0x00000400;
    private const uint ExtendedStartupInfoPresent = 0x00080000;
    private const int StartfUseStdHandles = 0x00000100;
    private const int HandleFlagInherit = 0x00000001;
    private const uint GenericRead = 0x80000000;
    private const uint FileShareReadWrite = 0x00000003;
    private const uint OpenExisting = 3;
    private const uint WaitObject0 = 0;
    private const uint WaitTimeout = 0x00000102;
    private const uint Infinite = 0xFFFFFFFF;
    private static readonly IntPtr ProcThreadAttributeHandleList = (IntPtr)0x00020002;
    private static readonly IntPtr ProcThreadAttributePseudoConsole = (IntPtr)0x00020016;
    private static readonly IntPtr InvalidHandleValue = new IntPtr(-1);

    private readonly bool _ownConsole;
    private readonly bool _pseudoConsole;

    private IntPtr _process;
    private IntPtr _thread;
    private bool _resumed;
    private bool _disposed;

    private ChildProcess(
        IntPtr process,
        IntPtr thread,
        int processId,
        StreamReader standardOutput,
        StreamReader standardError,
        StreamWriter? standardInput,
        bool ownConsole,
        bool pseudoConsole)
    {
        _process = process;
        _thread = thread;
        ProcessId = processId;
        StandardOutput = standardOutput;
        StandardError = standardError;
        StandardInput = standardInput;
        _ownConsole = ownConsole;
        _pseudoConsole = pseudoConsole;
    }

    public int ProcessId { get; }

    /// <summary>The raw process handle, for <see cref="JobObject.Assign"/>.</summary>
    public IntPtr Handle => _process;

    /// <summary>The child's stdout. Empty for a pseudo-console child, whose output is the
    /// console's (<see cref="ChildProcessStartInfo.PseudoConsole"/>).</summary>
    public StreamReader StandardOutput { get; }

    /// <summary>The child's stderr. Empty for a pseudo-console child: a console has one
    /// screen, and stderr is drawn on it.</summary>
    public StreamReader StandardError { get; }

    /// <summary>
    /// The child's stdin, when <see cref="ChildProcessStartInfo.RedirectStandardInput"/> asked
    /// for one; null otherwise, because the child was given `NUL` and there is nothing to write
    /// to. Auto-flushing: a JSON-RPC request that sat in a buffer would be a request the child
    /// never answers. Closing it is end of file for the child.
    /// </summary>
    public StreamWriter? StandardInput { get; }

    public bool HasExited => _process != IntPtr.Zero && WaitForSingleObject(_process, 0) == WaitObject0;

    public int ExitCode
    {
        get
        {
            if (_process == IntPtr.Zero || !GetExitCodeProcess(_process, out uint code))
            {
                return -1;
            }

            return unchecked((int)code);
        }
    }

    /// <summary>
    /// Creates the process with its initial thread suspended, and - this is the point of the
    /// overload - puts it in <paramref name="job"/> and <paramref name="nested"/> before
    /// returning. Call <see cref="Resume"/> when you are ready; nothing the child could do has
    /// happened when this returns.
    ///
    /// The jobs are assigned here rather than by the caller so the ordering cannot be got
    /// wrong: a caller that assigned after resuming would leave a window in which a
    /// fast-exiting child escapes the job, and that is invisible until the day SOLIDWORKS
    /// crashes and an orphan is found holding a port (T050).
    /// </summary>
    /// <param name="info">What to start, where, and with which environment.</param>
    /// <param name="job">The host's long-lived job: everything the pane starts is in it, and
    /// it is what the kernel closes when SOLIDWORKS dies without running any of our code.</param>
    /// <param name="nested">A job belonging to this one child, assigned second so it nests
    /// inside <paramref name="job"/> (nested jobs, Windows 8 and later). Closing it ends the
    /// child *and everything the child started* - which is the only way to stop
    /// `uv run ... swreview chat serve`, where the HTTP server is a generation below the
    /// process we hold a handle to.</param>
    public static ChildProcess StartSuspended(
        ChildProcessStartInfo info, JobObject? job = null, JobObject? nested = null)
    {
        if (info == null)
        {
            throw new ArgumentNullException(nameof(info));
        }

        var security = new SECURITY_ATTRIBUTES
        {
            nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES)),
            lpSecurityDescriptor = IntPtr.Zero,
            bInheritHandle = true,
        };

        // A pseudo-console child is given a console instead of pipes, so none of the pipe,
        // NUL, handle-list or std-handle machinery below applies to it.
        bool pty = info.PseudoConsole != IntPtr.Zero;

        IntPtr outRead = IntPtr.Zero;
        IntPtr outWrite = IntPtr.Zero;
        IntPtr errRead = IntPtr.Zero;
        IntPtr errWrite = IntPtr.Zero;
        IntPtr inRead = IntPtr.Zero;
        IntPtr inWrite = IntPtr.Zero;
        IntPtr nul = IntPtr.Zero;
        IntPtr attributeList = IntPtr.Zero;
        IntPtr handleArray = IntPtr.Zero;
        IntPtr environmentBlock = IntPtr.Zero;

        try
        {
            var startup = default(STARTUPINFOEX);
            startup.StartupInfo.cb = Marshal.SizeOf(typeof(STARTUPINFOEX));

            if (pty)
            {
                attributeList = BuildPseudoConsoleAttribute(info.PseudoConsole);

                // `STARTF_USESTDHANDLES` with three null handles, which reads like a
                // contradiction and is the whole thing working.
                //
                // Without it, `CreateProcess` gives the child *this* process's standard
                // handles, and it keeps them even though the pseudo-console attribute
                // attaches it to a different console. The child then draws its screen
                // wherever our stdout happens to point - measured: a `cmd.exe /c echo hello`
                // under a pseudo-console printed "hello" on the test runner's console and the
                // pseudo-console received only the console's own initialization bytes. In
                // SLDWORKS.exe, which has no standard handles at all, the same child writes
                // to nothing and the terminal stays empty for ever, and an interactive CLI
                // reading a standard input that is not its console exits at once.
                //
                // Saying "use these handles" and giving none stops the inheritance, and the
                // console driver then hands the child the pseudo-console's own handles, which
                // is what was wanted. `INVALID_HANDLE_VALUE` behaves identically; null is the
                // spelling that says "there is no handle here".
                startup.StartupInfo.dwFlags = StartfUseStdHandles;
                startup.StartupInfo.hStdInput = IntPtr.Zero;
                startup.StartupInfo.hStdOutput = IntPtr.Zero;
                startup.StartupInfo.hStdError = IntPtr.Zero;
            }
            else
            {
                CreatePipePair(ref security, out outRead, out outWrite);
                CreatePipePair(ref security, out errRead, out errWrite);

                if (info.RedirectStandardInput)
                {
                    CreateInputPipePair(ref security, out inRead, out inWrite);
                }
                else
                {
                    nul = CreateFile(
                        "NUL", GenericRead, FileShareReadWrite, ref security, OpenExisting, 0, IntPtr.Zero);
                    if (nul == InvalidHandleValue)
                    {
                        nul = IntPtr.Zero;
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "opening NUL for the child's stdin failed");
                    }
                }

                IntPtr childInput = info.RedirectStandardInput ? inRead : nul;
                attributeList = BuildHandleListAttribute(
                    new[] { childInput, outWrite, errWrite }, out handleArray);

                startup.StartupInfo.dwFlags = StartfUseStdHandles;
                startup.StartupInfo.hStdInput = childInput;
                startup.StartupInfo.hStdOutput = outWrite;
                startup.StartupInfo.hStdError = errWrite;
            }

            startup.lpAttributeList = attributeList;

            string commandLine = BuildCommandLine(info.Executable, info.Arguments);
            environmentBlock = BuildEnvironmentBlock(info);

            // A console is what a Ctrl+Break travels along, and a graceful stop is the only way
            // the backend's shutdown handler ever runs (see TryRequestStop). Two cases, and
            // both leave this process's own console exactly as it found it:
            //
            // - we have no console (SLDWORKS.exe, a GUI process): the child gets its own,
            //   window-less one, and TryRequestStop attaches to it for the length of one call;
            // - we have one (a console host, a test runner): the child inherits it, so no
            //   window appears and no attaching is needed at all.
            //
            // CREATE_NEW_PROCESS_GROUP in both cases: it makes the child the leader of a group
            // whose id is its pid, which is what GenerateConsoleCtrlEvent is given, so the
            // signal reaches the child and its descendants and nothing else on that console -
            // this process included.
            //
            // A pseudo-console child takes neither flag: it already has a console (the
            // pseudo-console, which has no window), and a new process group would start it
            // with Ctrl+C disabled - a terminal in which Ctrl+C does nothing is broken, and
            // that child is stopped by its exit command and its job, never by a signal.
            bool ownConsole = !pty && !HasConsole();
            uint creationFlags = CreateSuspended | CreateUnicodeEnvironment
                | ExtendedStartupInfoPresent;
            if (!pty)
            {
                creationFlags |= CreateNewProcessGroup;
                if (ownConsole)
                {
                    creationFlags |= CreateNoWindow;
                }
            }

            var created = default(PROCESS_INFORMATION);
            bool ok = CreateProcess(
                info.Executable,
                new StringBuilder(commandLine),
                IntPtr.Zero,
                IntPtr.Zero,
                bInheritHandles: !pty,
                dwCreationFlags: creationFlags,
                lpEnvironment: environmentBlock,
                lpCurrentDirectory: string.IsNullOrEmpty(info.WorkingDirectory) ? null : info.WorkingDirectory,
                lpStartupInfo: ref startup,
                lpProcessInformation: out created);

            if (!ok)
            {
                int error = Marshal.GetLastWin32Error();
                throw new Win32Exception(
                    error,
                    $"CreateProcess failed for '{info.Executable}': "
                    + new Win32Exception(error).Message);
            }

            StreamReader standardOutput = StreamReader.Null;
            StreamReader standardError = StreamReader.Null;
            StreamWriter? standardInput = null;
            if (!pty)
            {
                // The child owns the write ends now; keeping them open in the parent would mean
                // the reader below never sees end-of-file when the child exits.
                CloseHandle(outWrite);
                outWrite = IntPtr.Zero;
                CloseHandle(errWrite);
                errWrite = IntPtr.Zero;
                if (nul != IntPtr.Zero)
                {
                    CloseHandle(nul);
                    nul = IntPtr.Zero;
                }

                if (inRead != IntPtr.Zero)
                {
                    // The child's end, for the same reason as the write ends above: held open
                    // here, the child would never see end of file when we close ours.
                    CloseHandle(inRead);
                    inRead = IntPtr.Zero;

                    standardInput = new StreamWriter(
                        new FileStream(new SafeFileHandle(inWrite, ownsHandle: true), FileAccess.Write, 1, false),
                        new UTF8Encoding(false))
                    {
                        AutoFlush = true,
                    };
                    inWrite = IntPtr.Zero;
                }

                standardOutput = new StreamReader(
                    new FileStream(new SafeFileHandle(outRead, ownsHandle: true), FileAccess.Read, 1, false),
                    new UTF8Encoding(false));
                standardError = new StreamReader(
                    new FileStream(new SafeFileHandle(errRead, ownsHandle: true), FileAccess.Read, 1, false),
                    new UTF8Encoding(false));
                outRead = IntPtr.Zero;
                errRead = IntPtr.Zero;
            }

            var child = new ChildProcess(
                created.hProcess,
                created.hThread,
                created.dwProcessId,
                standardOutput,
                standardError,
                standardInput,
                ownConsole,
                pty);
            try
            {
                // The host's job first, the child's own job second: the second assignment is
                // what nests, so the per-child job ends up inside the host's rather than the
                // other way round.
                job?.Assign(child);
                nested?.Assign(child);
            }
            catch
            {
                // A child that could not be put in the job must not be left running: it is
                // exactly the orphan the job exists to prevent.
                child.Dispose();
                throw;
            }

            return child;
        }
        catch
        {
            CloseIfSet(outRead);
            CloseIfSet(outWrite);
            CloseIfSet(errRead);
            CloseIfSet(errWrite);
            CloseIfSet(inRead);
            CloseIfSet(inWrite);
            CloseIfSet(nul);
            throw;
        }
        finally
        {
            if (attributeList != IntPtr.Zero)
            {
                DeleteProcThreadAttributeList(attributeList);
                Marshal.FreeHGlobal(attributeList);
            }

            if (handleArray != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(handleArray);
            }

            if (environmentBlock != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(environmentBlock);
            }
        }
    }

    /// <summary>Lets the child's initial thread run. Idempotent.</summary>
    public void Resume()
    {
        if (_resumed || _thread == IntPtr.Zero)
        {
            return;
        }

        if (ResumeThread(_thread) == unchecked((uint)-1))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "ResumeThread failed");
        }

        _resumed = true;
    }

    public bool WaitForExit(int milliseconds)
    {
        if (_process == IntPtr.Zero)
        {
            return true;
        }

        uint wait = WaitForSingleObject(_process, milliseconds < 0 ? Infinite : (uint)milliseconds);
        return wait != WaitTimeout;
    }

    /// <summary>
    /// Asks the child to shut down the way Ctrl+Break does, and says whether the signal was
    /// delivered. The caller waits for the exit and falls back to <see cref="Kill"/>.
    ///
    /// This exists because <see cref="Kill"/> cannot replace it. `TerminateProcess` delivers no
    /// signal at all: the child's handlers never run, its `atexit` never runs, and for the
    /// Python backend that means uvicorn's shutdown - the lifespan that finalizes every live
    /// chat and writes an `ended_at` - is dead code in production (chat-api.md, "Shutdown and
    /// settings changes"; FR-008 says a session is never left without an ended time). uvicorn
    /// handles `SIGBREAK` on Windows, which is what a `CTRL_BREAK_EVENT` becomes, so this is
    /// the signal to send; `CTRL_C_EVENT` is not, because a process created with
    /// `CREATE_NEW_PROCESS_GROUP` starts with Ctrl+C disabled.
    ///
    /// The signal is addressed to the child's process group, which is the child and everything
    /// it started, so the real launcher shape - `uv run ... swreview chat serve`, where the
    /// server is a grandchild - is reached too.
    ///
    /// False means nothing was sent - no console to send it along, the child already gone -
    /// and never that the child refused; the caller must still be prepared to terminate it.
    /// </summary>
    public bool TryRequestStop()
    {
        if (_process == IntPtr.Zero || !_resumed || HasExited)
        {
            return false;
        }

        if (_pseudoConsole)
        {
            // The child's console is the pseudo-console, not ours, and attaching to it would
            // put this process on a console belonging to a conhost we do not own. A terminal
            // child is asked to stop by writing its exit command into that console and ended
            // by its job (Terminal/TerminalSession.cs).
            return false;
        }

        if (!_ownConsole)
        {
            // The child is on our console already.
            return Signal();
        }

        // We had no console when the child was created, so it has one of its own and we have
        // to be on it to signal along it. Attaching is safe precisely because we started with
        // none: the FreeConsole below restores exactly the state we were in.
        if (!AttachConsole((uint)ProcessId))
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(), $"attaching to the console of process {ProcessId} failed");
        }

        try
        {
            return Signal();
        }
        finally
        {
            FreeConsole();
        }
    }

    private bool Signal()
    {
        if (GenerateConsoleCtrlEvent(CtrlBreakEvent, (uint)ProcessId))
        {
            return true;
        }

        throw new Win32Exception(
            Marshal.GetLastWin32Error(),
            $"sending CTRL_BREAK_EVENT to process group {ProcessId} failed");
    }

    /// <summary>Ends the process now. Safe to call on one that has already exited.</summary>
    public void Kill()
    {
        if (_process == IntPtr.Zero || HasExited)
        {
            return;
        }

        // A suspended process still has to be resumed before it can be terminated cleanly on
        // some Windows versions; terminating is reliable either way, so resume first.
        Resume();
        TerminateProcess(_process, 1);
        WaitForSingleObject(_process, 5000);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        try
        {
            Kill();
        }
        catch (Win32Exception)
        {
            // Cleanup must not throw out of a `using` that is already unwinding.
        }

        try
        {
            StandardInput?.Dispose();
        }
        catch (IOException)
        {
            // The child has gone and taken the read end of the pipe with it.
        }

        StandardOutput.Dispose();
        StandardError.Dispose();

        if (_thread != IntPtr.Zero)
        {
            CloseHandle(_thread);
            _thread = IntPtr.Zero;
        }

        if (_process != IntPtr.Zero)
        {
            CloseHandle(_process);
            _process = IntPtr.Zero;
        }
    }

    /// <summary>
    /// One command line from an executable and its arguments, quoted the way `CommandLineToArgvW`
    /// parses it back: a run of backslashes before a quote doubles, and an argument containing a
    /// space, a tab or a quote is wrapped.
    /// </summary>
    public static string BuildCommandLine(string executable, IEnumerable<string> arguments)
    {
        var builder = new StringBuilder();
        builder.Append(Quote(executable));
        foreach (string argument in arguments ?? Enumerable.Empty<string>())
        {
            builder.Append(' ').Append(Quote(argument));
        }

        return builder.ToString();
    }

    /// <summary>One argument, quoted for a Windows command line.</summary>
    private static string Quote(string argument)
    {
        if (argument == null)
        {
            throw new ArgumentNullException(nameof(argument));
        }

        if (argument.Length > 0 && argument.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
        {
            return argument;
        }

        var builder = new StringBuilder("\"");
        for (int index = 0; index < argument.Length; index++)
        {
            int backslashes = 0;
            while (index < argument.Length && argument[index] == '\\')
            {
                backslashes++;
                index++;
            }

            if (index == argument.Length)
            {
                builder.Append('\\', backslashes * 2);
                break;
            }

            if (argument[index] == '"')
            {
                builder.Append('\\', (backslashes * 2) + 1).Append('"');
            }
            else
            {
                builder.Append('\\', backslashes).Append(argument[index]);
            }
        }

        return builder.Append('"').ToString();
    }

    /// <summary>
    /// Whether this process is attached to a console.
    ///
    /// `GetConsoleWindow` is the obvious probe and the wrong one: it answers "is there a
    /// console *window*", and a console created with `CREATE_NO_WINDOW` - which is how a test
    /// runner is typically launched, and how this class starts its own children - has none.
    /// A process that answered "no console" on that basis and then called `AttachConsole`
    /// would be refused with ERROR_ACCESS_DENIED, because it already had one.
    /// `GetConsoleProcessList` asks the question that is actually being asked.
    /// </summary>
    private static bool HasConsole()
    {
        var processes = new uint[1];
        return GetConsoleProcessList(processes, 1) != 0;
    }

    private static void CreatePipePair(ref SECURITY_ATTRIBUTES security, out IntPtr read, out IntPtr write)
    {
        if (!CreatePipe(out read, out write, ref security, 0))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "CreatePipe failed");
        }

        // Only the child's end is inheritable; ours must not leak into any other child.
        if (!SetHandleInformation(read, HandleFlagInherit, 0))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "SetHandleInformation failed");
        }
    }

    /// <summary>
    /// A pipe for the child's standard input: the mirror of <see cref="CreatePipePair"/>.
    ///
    /// The ends swap roles, and the swap is not cosmetic. For stdout and stderr the child owns
    /// the write end, so the read end has its inherit flag cleared; for stdin the child owns the
    /// *read* end, so it is the write end that must not be inheritable. Handing the handle-list
    /// attribute a non-inheritable handle fails `CreateProcess` with ERROR_INVALID_PARAMETER,
    /// which says nothing about which handle or why.
    /// </summary>
    private static void CreateInputPipePair(
        ref SECURITY_ATTRIBUTES security, out IntPtr read, out IntPtr write)
    {
        if (!CreatePipe(out read, out write, ref security, 0))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "CreatePipe failed");
        }

        if (!SetHandleInformation(write, HandleFlagInherit, 0))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "SetHandleInformation failed");
        }
    }

    private static IntPtr BuildHandleListAttribute(IntPtr[] handles, out IntPtr handleArray)
    {
        IntPtr size = IntPtr.Zero;
        InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
        IntPtr list = Marshal.AllocHGlobal(size);
        if (!InitializeProcThreadAttributeList(list, 1, 0, ref size))
        {
            int error = Marshal.GetLastWin32Error();
            Marshal.FreeHGlobal(list);
            throw new Win32Exception(error, "InitializeProcThreadAttributeList failed");
        }

        handleArray = Marshal.AllocHGlobal(IntPtr.Size * handles.Length);
        Marshal.Copy(handles, 0, handleArray, handles.Length);

        if (!UpdateProcThreadAttribute(
                list,
                0,
                ProcThreadAttributeHandleList,
                handleArray,
                (IntPtr)(IntPtr.Size * handles.Length),
                IntPtr.Zero,
                IntPtr.Zero))
        {
            int error = Marshal.GetLastWin32Error();
            DeleteProcThreadAttributeList(list);
            Marshal.FreeHGlobal(list);
            Marshal.FreeHGlobal(handleArray);
            handleArray = IntPtr.Zero;
            throw new Win32Exception(error, "UpdateProcThreadAttribute(handle list) failed");
        }

        return list;
    }

    /// <summary>
    /// An attribute list carrying `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`.
    ///
    /// Unlike the handle list, the value *is* the `HPCON` rather than a pointer to a buffer of
    /// them, so there is nothing to allocate and nothing to free but the list itself.
    /// </summary>
    private static IntPtr BuildPseudoConsoleAttribute(IntPtr console)
    {
        IntPtr size = IntPtr.Zero;
        InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
        IntPtr list = Marshal.AllocHGlobal(size);
        if (!InitializeProcThreadAttributeList(list, 1, 0, ref size))
        {
            int error = Marshal.GetLastWin32Error();
            Marshal.FreeHGlobal(list);
            throw new Win32Exception(error, "InitializeProcThreadAttributeList failed");
        }

        if (!UpdateProcThreadAttribute(
                list,
                0,
                ProcThreadAttributePseudoConsole,
                console,
                (IntPtr)IntPtr.Size,
                IntPtr.Zero,
                IntPtr.Zero))
        {
            int error = Marshal.GetLastWin32Error();
            DeleteProcThreadAttributeList(list);
            Marshal.FreeHGlobal(list);
            throw new Win32Exception(error, "UpdateProcThreadAttribute(pseudoconsole) failed");
        }

        return list;
    }

    /// <summary>
    /// The parent's environment plus the overrides, as the sorted, double-null-terminated
    /// Unicode block `CREATE_UNICODE_ENVIRONMENT` expects.
    /// </summary>
    private static IntPtr BuildEnvironmentBlock(ChildProcessStartInfo info)
    {
        var merged = new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (DictionaryEntry entry in Environment.GetEnvironmentVariables())
        {
            string name = (string)entry.Key;
            // "=C:" style entries record per-drive working directories; they are not settings
            // and a sorted block that contains them confuses some runtimes.
            if (name.Length > 0 && name[0] != '=')
            {
                merged[name] = entry.Value as string ?? string.Empty;
            }
        }

        foreach (KeyValuePair<string, string> entry in info.Environment)
        {
            merged[entry.Key] = entry.Value ?? string.Empty;
        }

        var builder = new StringBuilder();
        foreach (KeyValuePair<string, string> entry in merged)
        {
            builder.Append(entry.Key).Append('=').Append(entry.Value).Append('\0');
        }

        builder.Append('\0');
        return Marshal.StringToHGlobalUni(builder.ToString());
    }

    private static void CloseIfSet(IntPtr handle)
    {
        if (handle != IntPtr.Zero && handle != InvalidHandleValue)
        {
            CloseHandle(handle);
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        [MarshalAs(UnmanagedType.Bool)]
        public bool bInheritHandle;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public int dwProcessId;
        public int dwThreadId;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int cb;
        public IntPtr lpReserved;
        public IntPtr lpDesktop;
        public IntPtr lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFOEX
    {
        public STARTUPINFO StartupInfo;
        public IntPtr lpAttributeList;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreatePipe(
        out IntPtr readPipe, out IntPtr writePipe, ref SECURITY_ATTRIBUTES attributes, int size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetHandleInformation(IntPtr handle, int mask, int flags);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        ref SECURITY_ATTRIBUTES securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InitializeProcThreadAttributeList(
        IntPtr attributeList, int attributeCount, int flags, ref IntPtr size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateProcThreadAttribute(
        IntPtr attributeList,
        uint flags,
        IntPtr attribute,
        IntPtr value,
        IntPtr size,
        IntPtr previousValue,
        IntPtr returnSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern void DeleteProcThreadAttributeList(IntPtr attributeList);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcess(
        string? lpApplicationName,
        StringBuilder lpCommandLine,
        IntPtr lpProcessAttributes,
        IntPtr lpThreadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool bInheritHandles,
        uint dwCreationFlags,
        IntPtr lpEnvironment,
        string? lpCurrentDirectory,
        ref STARTUPINFOEX lpStartupInfo,
        out PROCESS_INFORMATION lpProcessInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr thread);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint GetConsoleProcessList(uint[] processList, uint count);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AttachConsole(uint processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool FreeConsole();

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GenerateConsoleCtrlEvent(uint ctrlEvent, uint processGroupId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(IntPtr process, uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
