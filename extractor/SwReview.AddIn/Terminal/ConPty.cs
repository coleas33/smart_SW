using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace SwReview.AddIn.Terminal;

/// <summary>
/// A Windows pseudo-console: a console the add-in owns, with the CLI on the far side of it
/// and two pipes on this side (research.md R5).
///
/// Why this rather than redirected pipes: both CLIs are full-screen console applications.
/// Given a pipe instead of a console they see `GetConsoleMode` fail, decide they are not
/// interactive, and either refuse to run their TUI or fall back to a line mode with no
/// prompts - and nothing would ever deliver a window size, so the TUI would draw into a box
/// of the wrong shape. A pseudo-console is a real console as far as the child is concerned:
/// its screen arrives here as VT bytes, and keystrokes go back the same way, which is exactly
/// what xterm.js consumes and produces.
///
/// Why not a console window reparented into the pane: `SetParent` on a console window is
/// unsupported and breaks input focus and DPI (research.md R5). Never used.
///
/// Two ownership rules that are easy to get wrong:
///
/// <b>Closing this ends the child.</b> `ClosePseudoConsole` takes the console away, and a
/// client left without one is signalled to exit. That is the stop path that still works when
/// the CLI has stopped reading its input, so <see cref="Dispose"/> is not optional cleanup -
/// it is how a closed pane ends a hung CLI.
///
/// <b>Something must be reading <see cref="Output"/> when it closes.</b>
/// `ClosePseudoConsole` flushes what the child has written before it returns, so a caller
/// that stopped reading first can hang inside it. <see cref="TerminalSession"/> closes from
/// its watcher while the read loop is still running, which is the shape that works.
/// </summary>
public sealed class ConPty : IDisposable
{
    /// <summary>`PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`, the attribute that hands a child this
    /// console instead of the parent's (<see cref="Native.ChildProcessStartInfo.PseudoConsole"/>).</summary>
    internal static readonly IntPtr ProcThreadAttributePseudoConsole = (IntPtr)0x00020016;

    private static readonly IntPtr InvalidHandleValue = new IntPtr(-1);

    private readonly object _gate = new object();

    private IntPtr _handle;
    private bool _disposed;

    private ConPty(IntPtr handle, FileStream output, FileStream input, short columns, short rows)
    {
        _handle = handle;
        Output = output;
        Input = input;
        Columns = columns;
        Rows = rows;
    }

    /// <summary>The `HPCON`, for the process attribute. Zero once disposed.</summary>
    public IntPtr Handle
    {
        get
        {
            lock (_gate)
            {
                return _handle;
            }
        }
    }

    /// <summary>What the child drew, as raw bytes. Read it on a thread of its own: reads block
    /// until the child writes, and end only when the console closes.</summary>
    public Stream Output { get; }

    /// <summary>Keystrokes for the child, as raw bytes.</summary>
    public Stream Input { get; }

    public short Columns { get; private set; }

    public short Rows { get; private set; }

    /// <summary>Creates a pseudo-console of the given size.</summary>
    public static ConPty Create(short columns, short rows)
    {
        if (columns <= 0 || rows <= 0)
        {
            throw new ArgumentOutOfRangeException(
                columns <= 0 ? nameof(columns) : nameof(rows),
                "a pseudo-console needs a positive width and height");
        }

        IntPtr inputRead = IntPtr.Zero;
        IntPtr inputWrite = IntPtr.Zero;
        IntPtr outputRead = IntPtr.Zero;
        IntPtr outputWrite = IntPtr.Zero;
        IntPtr console = IntPtr.Zero;

        try
        {
            CreatePipePair(out inputRead, out inputWrite);
            CreatePipePair(out outputRead, out outputWrite);

            // The console reads the child's keystrokes from `inputRead` and writes the child's
            // screen to `outputWrite`; we keep the other end of each.
            int result = CreatePseudoConsole(
                new COORD { X = columns, Y = rows }, inputRead, outputWrite, 0, out console);
            if (result != 0)
            {
                throw new Win32Exception(
                    result,
                    "CreatePseudoConsole failed. A pseudo-console needs Windows 10 1809 or "
                    + "later; Windows 11 is this add-in's baseline.");
            }

            // The console duplicated both of them, so our copies are dead weight - and worse
            // than dead: an open copy of `outputWrite` here would mean the read below never
            // sees end of file when the console closes.
            CloseHandle(inputRead);
            inputRead = IntPtr.Zero;
            CloseHandle(outputWrite);
            outputWrite = IntPtr.Zero;

            // Unbuffered, because a terminal is a stream of bytes that matter the moment they
            // arrive: a buffered reader would hold a half-drawn frame back waiting to fill.
            var output = new FileStream(
                new SafeFileHandle(outputRead, ownsHandle: true), FileAccess.Read, 1, isAsync: false);
            outputRead = IntPtr.Zero;
            var input = new FileStream(
                new SafeFileHandle(inputWrite, ownsHandle: true), FileAccess.Write, 1, isAsync: false);
            inputWrite = IntPtr.Zero;

            var conpty = new ConPty(console, output, input, columns, rows);
            console = IntPtr.Zero;
            return conpty;
        }
        finally
        {
            if (console != IntPtr.Zero)
            {
                ClosePseudoConsole(console);
            }

            CloseIfSet(inputRead);
            CloseIfSet(inputWrite);
            CloseIfSet(outputRead);
            CloseIfSet(outputWrite);
        }
    }

    /// <summary>
    /// Tells the child the terminal is a different shape. Ignored once the console is closed:
    /// a resize arriving from the page while the CLI is exiting is ordinary, not an error.
    /// </summary>
    public void Resize(short columns, short rows)
    {
        if (columns <= 0 || rows <= 0)
        {
            throw new ArgumentOutOfRangeException(
                columns <= 0 ? nameof(columns) : nameof(rows),
                "a pseudo-console needs a positive width and height");
        }

        lock (_gate)
        {
            if (_handle == IntPtr.Zero)
            {
                return;
            }

            int result = ResizePseudoConsole(_handle, new COORD { X = columns, Y = rows });
            if (result != 0)
            {
                throw new Win32Exception(result, "ResizePseudoConsole failed");
            }

            Columns = columns;
            Rows = rows;
        }
    }

    /// <summary>
    /// Closes the console, which ends whatever was attached to it, and then the pipes.
    /// Idempotent. See the class remarks: something has to be reading <see cref="Output"/>.
    /// </summary>
    public void Dispose()
    {
        IntPtr console;
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            console = _handle;
            _handle = IntPtr.Zero;
        }

        if (console != IntPtr.Zero)
        {
            ClosePseudoConsole(console);
        }

        // After the console, never before: the reader is given its end of file by the close
        // above, and disposing its stream first would turn that into an exception instead.
        try
        {
            Output.Dispose();
        }
        catch (IOException)
        {
        }

        try
        {
            Input.Dispose();
        }
        catch (IOException)
        {
        }
    }

    private static void CreatePipePair(out IntPtr read, out IntPtr write)
    {
        var security = new SECURITY_ATTRIBUTES
        {
            nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES)),
            lpSecurityDescriptor = IntPtr.Zero,
            // Nothing here is inherited: the console duplicates what it needs, and the child
            // is given the console, not the pipes.
            bInheritHandle = false,
        };

        if (!CreatePipe(out read, out write, ref security, 0))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "CreatePipe failed");
        }
    }

    private static void CloseIfSet(IntPtr handle)
    {
        if (handle != IntPtr.Zero && handle != InvalidHandleValue)
        {
            CloseHandle(handle);
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct COORD
    {
        public short X;
        public short Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        [MarshalAs(UnmanagedType.Bool)]
        public bool bInheritHandle;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreatePipe(
        out IntPtr readPipe, out IntPtr writePipe, ref SECURITY_ATTRIBUTES attributes, int size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = false)]
    private static extern int CreatePseudoConsole(
        COORD size, IntPtr input, IntPtr output, uint flags, out IntPtr console);

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = false)]
    private static extern int ResizePseudoConsole(IntPtr console, COORD size);

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = false)]
    private static extern void ClosePseudoConsole(IntPtr console);
}
