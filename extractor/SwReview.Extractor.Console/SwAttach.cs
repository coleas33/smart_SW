using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

namespace SwReview.Extractor.Console;

/// <summary>
/// Gets hold of SOLIDWORKS from outside its process.
///
/// Attach-only by default. <c>Activator.CreateInstance</c> starts a session with no add-ins
/// and, more importantly, with none of the documents the engineer has open - so a dump
/// would silently describe a different model than the one on screen (research R12). Worse,
/// nothing in this tree ever closes that session, so it sits invisible holding a licence.
/// Starting one is therefore opt-in, with <c>--allow-start</c>, for an unattended script.
///
/// Both paths use the SAME ProgID. They used not to: the running-object-table lookup asked
/// for version-independent "SldWorks.Application" while the create asked for
/// "SldWorks.Application.32", so on a machine where the two resolve to different CLSIDs the
/// lookup could miss the running 2024 seat and then start a second one by the other route.
/// (On the pilot workstation both currently resolve to {AFBEC3B2-B1A6-4908-B608-D97D2AAB5498};
/// the versioned ProgID is the one research R12 pins to 2024, so it is the one used.)
/// </summary>
public static class SwAttach
{
    /// <summary>The out-of-process ProgID for SOLIDWORKS 2024 (research R12).</summary>
    public const string ProgId = "SldWorks.Application.32";

    /// <summary>The image name of the SOLIDWORKS process, without the extension.</summary>
    private const string ProcessName = "SLDWORKS";

    private const uint TokenQuery = 0x0008;

    private const int TokenIntegrityLevel = 25;

    /// <summary>
    /// PROCESS_QUERY_LIMITED_INFORMATION (Vista and later). Deliberately NOT
    /// <see cref="Process.Handle"/>, whose getter opens PROCESS_ALL_ACCESS: a
    /// medium-integrity console can never get that on an elevated SLDWORKS.exe, so the one
    /// case this whole diagnosis exists for would always read its integrity level as
    /// "unreadable". This right is granted across integrity levels for the same user, which
    /// is what makes the "high versus medium" sentence reachable in production.
    /// </summary>
    private const uint ProcessQueryLimitedInformation = 0x1000;

    /// <summary>
    /// The running session. <paramref name="allowStart"/> (from <c>--allow-start</c>) also
    /// permits starting a new one when nothing is running; without it, a failed attach is
    /// an error that says which fact differs. <paramref name="started"/> says which
    /// happened, so the caller can log it: a dump against a freshly started session is a
    /// different situation from one against the engineer's own.
    ///
    /// <paramref name="attachDiagnosis"/> is the same sentence the attach-only error carries,
    /// handed back on the start path when an SLDWORKS.exe WAS running that COM could not see,
    /// and null otherwise. A successful <c>CreateInstance</c> is not evidence that nothing was
    /// running (constitution, Principle I) - on a single-instance COM server it may even have
    /// bound an existing invisible seat - so the caller must not claim that, and the engineer
    /// gets the elevation diagnosis on this path too.
    /// </summary>
    public static ISldWorks Connect(bool allowStart, out bool started, out string? attachDiagnosis)
    {
        ISldWorks? running = TryGetRunning();
        if (running != null)
        {
            started = false;
            attachDiagnosis = null;
            return running;
        }

        Process self = Process.GetCurrentProcess();
        int ourSessionId = self.SessionId;
        string ourIntegrityLevel = IntegrityLevelOf(self) ?? "unknown";
        IReadOnlyList<SwProcessFacts> found = MeasureSolidWorksProcesses();

        if (!allowStart)
        {
            throw new InvalidOperationException(
                AttachFailure.Describe(ProgId, ourSessionId, ourIntegrityLevel, found));
        }

        attachDiagnosis = found.Count == 0
            ? null
            : AttachFailure.Diagnose(ourSessionId, ourIntegrityLevel, found);

        Type? type = Type.GetTypeFromProgID(ProgId);
        if (type == null)
        {
            throw new InvalidOperationException(
                $"SOLIDWORKS is not installed, or the '{ProgId}' ProgID is not registered. "
                + "This host must run on the workstation, built for x64.");
        }

        var created = Activator.CreateInstance(type) as ISldWorks;
        if (created == null)
        {
            throw new InvalidOperationException($"Creating '{ProgId}' did not return an ISldWorks.");
        }

        // "started" means this path was taken, not that a process was created: on a
        // single-instance COM server CreateInstance may have bound an existing invisible
        // seat. The caller's log line says only that much.
        started = true;
        return created;
    }

    /// <summary>
    /// The instance in the running object table, or null. A missing entry throws
    /// COMException rather than returning null - but "missing" does NOT mean "nothing is
    /// running", which is why the caller diagnoses rather than assumes.
    /// </summary>
    private static ISldWorks? TryGetRunning()
    {
        try
        {
            return Marshal.GetActiveObject(ProgId) as ISldWorks;
        }
        catch (COMException)
        {
            return null;
        }
    }

    /// <summary>
    /// What this process can see of every SLDWORKS.exe. Measuring is this class's job;
    /// wording the result is <see cref="AttachFailure"/>'s, so both the attach-only error
    /// and the <c>--allow-start</c> log line say the same thing.
    /// </summary>
    private static IReadOnlyList<SwProcessFacts> MeasureSolidWorksProcesses()
    {
        var found = new List<SwProcessFacts>();
        foreach (Process process in Process.GetProcessesByName(ProcessName))
        {
            using (process)
            {
                found.Add(new SwProcessFacts(
                    process.Id, SessionIdOf(process), IntegrityLevelOf(process)));
            }
        }

        return found;
    }

    /// <summary>
    /// The process's Windows session, or null when it cannot be read - which happens for a
    /// process of another user, and is a diagnosis in itself.
    /// </summary>
    private static int? SessionIdOf(Process process)
    {
        try
        {
            return process.SessionId;
        }
        catch (InvalidOperationException)
        {
            return null;
        }
        catch (Win32Exception)
        {
            return null;
        }
    }

    /// <summary>
    /// "low", "medium", "high" or "system" from the process token's integrity level SID, or
    /// null when the token cannot be opened - which, with PROCESS_QUERY_LIMITED_INFORMATION,
    /// means another user's process rather than merely an elevated one of ours.
    /// </summary>
    private static string? IntegrityLevelOf(Process process)
    {
        IntPtr handle = IntPtr.Zero;
        IntPtr token = IntPtr.Zero;
        IntPtr buffer = IntPtr.Zero;

        try
        {
            handle = OpenProcess(ProcessQueryLimitedInformation, false, process.Id);
            if (handle == IntPtr.Zero)
            {
                return null;
            }

            if (!OpenProcessToken(handle, TokenQuery, out token))
            {
                return null;
            }

            int needed;
            GetTokenInformation(token, TokenIntegrityLevel, IntPtr.Zero, 0, out needed);
            if (needed <= 0)
            {
                return null;
            }

            buffer = Marshal.AllocHGlobal(needed);
            if (!GetTokenInformation(token, TokenIntegrityLevel, buffer, needed, out needed))
            {
                return null;
            }

            // TOKEN_MANDATORY_LABEL is a SID_AND_ATTRIBUTES: the SID pointer comes first.
            IntPtr sid = Marshal.ReadIntPtr(buffer);
            IntPtr countPointer = GetSidSubAuthorityCount(sid);
            if (countPointer == IntPtr.Zero)
            {
                return null;
            }

            int last = Marshal.ReadByte(countPointer) - 1;
            if (last < 0)
            {
                return null;
            }

            return NameOfIntegrityRid(Marshal.ReadInt32(GetSidSubAuthority(sid, (uint)last)));
        }
        catch (InvalidOperationException)
        {
            // Process.Id on a Process object whose process exited between the enumeration
            // and this call.
            return null;
        }
        finally
        {
            if (buffer != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(buffer);
            }

            if (token != IntPtr.Zero)
            {
                CloseHandle(token);
            }

            if (handle != IntPtr.Zero)
            {
                CloseHandle(handle);
            }
        }
    }

    /// <summary>
    /// The mandatory integrity RIDs from winnt.h: SECURITY_MANDATORY_LOW_RID 0x1000,
    /// MEDIUM 0x2000, HIGH 0x3000, SYSTEM 0x4000. An unnamed RID is reported as its hex
    /// value rather than rounded to the nearest name.
    /// </summary>
    private static string NameOfIntegrityRid(int rid)
    {
        switch (rid)
        {
            case 0x1000:
                return "low";
            case 0x2000:
                return "medium";
            case 0x3000:
                return "high";
            case 0x4000:
                return "system";
            default:
                return rid < 0x1000
                    ? "untrusted"
                    : "0x" + rid.ToString("X4", CultureInfo.InvariantCulture);
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(
        uint access, [MarshalAs(UnmanagedType.Bool)] bool inheritHandle, int processId);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetTokenInformation(
        IntPtr token, int informationClass, IntPtr information, int length, out int needed);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern IntPtr GetSidSubAuthority(IntPtr sid, uint index);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern IntPtr GetSidSubAuthorityCount(IntPtr sid);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
