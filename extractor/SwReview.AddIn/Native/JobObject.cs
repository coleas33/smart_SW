using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace SwReview.AddIn.Native;

/// <summary>
/// A Windows job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: every process assigned to
/// it dies when the last handle to the job closes.
///
/// This is the only cleanup mechanism that still works when the parent dies without running
/// any code of its own - SOLIDWORKS crashing, the add-in being torn down without
/// `DisconnectFromSW`, a debugger stopping the process. Handles are closed by the kernel on
/// process exit, so the kernel is what kills the children. Stopping each child politely on
/// unload is still done (<see cref="ChildProcess.Kill"/>); the job is what makes it certain.
///
/// Assignment order matters and is the reason <see cref="ChildProcess.StartSuspended"/>
/// exists: a child assigned after it has begun running has already had a window in which it
/// could exit or spawn outside the job. Create suspended, assign, then resume.
///
/// Nested jobs are supported from Windows 8 onward, so a SOLIDWORKS process that is itself in
/// a job (an App-V or MSIX container, a CI agent) does not prevent this one.
/// </summary>
public sealed class JobObject : IDisposable
{
    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JobObjectLimitKillOnJobClose = 0x00002000;
    private const uint ProcessQueryLimitedInformation = 0x1000;

    private IntPtr _handle;

    /// <summary>Creates an unnamed job that kills its members when this object is disposed.</summary>
    public JobObject()
    {
        _handle = CreateJobObject(IntPtr.Zero, null);
        if (_handle == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObject failed");
        }

        var limits = default(JOBOBJECT_EXTENDED_LIMIT_INFORMATION);
        limits.BasicLimitInformation.LimitFlags = JobObjectLimitKillOnJobClose;

        int size = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(limits, buffer, fDeleteOld: false);
            if (!SetInformationJobObject(_handle, JobObjectExtendedLimitInformation, buffer, (uint)size))
            {
                int error = Marshal.GetLastWin32Error();
                CloseHandle(_handle);
                _handle = IntPtr.Zero;
                throw new Win32Exception(error, "SetInformationJobObject(kill on job close) failed");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    /// <summary>Puts <paramref name="child"/> in this job. Call it while the child is still
    /// suspended; see the class remarks.</summary>
    public void Assign(ChildProcess child)
    {
        if (child == null)
        {
            throw new ArgumentNullException(nameof(child));
        }

        ThrowIfClosed();
        if (!AssignProcessToJobObject(_handle, child.Handle))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "AssignProcessToJobObject failed");
        }
    }

    /// <summary>Whether the process is a member of this job. False for a process that is gone.</summary>
    public bool Contains(int processId)
    {
        ThrowIfClosed();
        IntPtr process = OpenProcess(ProcessQueryLimitedInformation, bInheritHandle: false, dwProcessId: processId);
        if (process == IntPtr.Zero)
        {
            return false;
        }

        try
        {
            if (!IsProcessInJob(process, _handle, out bool member))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "IsProcessInJob failed");
            }

            return member;
        }
        finally
        {
            CloseHandle(process);
        }
    }

    /// <summary>Closes the job, which kills everything still in it.</summary>
    public void Dispose()
    {
        if (_handle != IntPtr.Zero)
        {
            CloseHandle(_handle);
            _handle = IntPtr.Zero;
        }
    }

    private void ThrowIfClosed()
    {
        if (_handle == IntPtr.Zero)
        {
            throw new ObjectDisposedException(nameof(JobObject));
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr securityAttributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(
        IntPtr job, int infoClass, IntPtr info, uint infoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsProcessInJob(
        IntPtr process, IntPtr job, [MarshalAs(UnmanagedType.Bool)] out bool result);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(
        uint desiredAccess, [MarshalAs(UnmanagedType.Bool)] bool bInheritHandle, int dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
