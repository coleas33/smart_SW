using System;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

namespace SwReview.Extractor.Console;

/// <summary>
/// Gets hold of SOLIDWORKS from outside its process.
///
/// The running instance comes FIRST, always. <c>Activator.CreateInstance</c> starts a
/// session with no add-ins and, more importantly, with none of the documents the engineer
/// has open - so a dump would silently describe a different model than the one on screen
/// (research R12). Starting a new session is the fallback for an unattended script.
/// </summary>
public static class SwAttach
{
    /// <summary>The out-of-process ProgID for SOLIDWORKS 2024 (research R12).</summary>
    public const string ProgId = "SldWorks.Application.32";

    /// <summary>
    /// The running session if there is one, otherwise a new one. <paramref name="started"/>
    /// says which, so the caller can log it: a dump against a freshly started session is a
    /// different situation from one against the engineer's own.
    /// </summary>
    public static ISldWorks Connect(out bool started)
    {
        ISldWorks? running = TryGetRunning();
        if (running != null)
        {
            started = false;
            return running;
        }

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

        started = true;
        return created;
    }

    /// <summary>
    /// The instance in the running object table, or null. A missing entry throws
    /// COMException rather than returning null, which is the normal "nothing is running"
    /// answer and not an error.
    /// </summary>
    private static ISldWorks? TryGetRunning()
    {
        try
        {
            return Marshal.GetActiveObject("SldWorks.Application") as ISldWorks;
        }
        catch (COMException)
        {
            return null;
        }
    }
}
