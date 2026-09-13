using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;

namespace SwReview.AddIn;

/// <summary>
/// In-process SOLIDWORKS 2024 add-in host (research R1: in-process traversal is 10 to 100x
/// faster than out-of-process COM, and several many-parameter API members fail late-bound).
///
/// This is the T004 skeleton: it connects and disconnects, and holds the ISldWorks pointer
/// every dumper will be handed. The Task Pane with the Dump IR, Interference and Capture
/// buttons is T060 and T076; nothing here touches a model yet.
///
/// Registration (research R12, "Add-in hosting"). The add-in is found through COM, not by
/// being copied anywhere, so both steps are required and both need an elevated x64 prompt:
///
///   1. Register the assembly for COM, recording this build output path:
///        "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\regasm.exe" /codebase SwReview.AddIn.dll
///
///   2. Tell SOLIDWORKS to load it, under the same GUID as <see cref="AddInGuid"/>:
///        HKLM\SOFTWARE\SOLIDWORKS\AddIns\{5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55}
///            (Default)    REG_DWORD  1        load at startup
///            Description  REG_SZ     "SwReview evidence extractor"
///            Title        REG_SZ     "SwReview"
///        HKCU\SOFTWARE\SOLIDWORKS\AddInsStartup\{5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55}
///            (Default)    REG_DWORD  1        per-user enable
///
///   Build x64 and reference the interops from the seat install
///   (C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist) with Embed Interop Types
///   false; the NuGet SolidWorks.Interop packages are community published and are not used.
///
/// The registry writes are done by [ComRegisterFunction] / [ComUnregisterFunction] methods
/// added in T060 alongside the Task Pane, so registration and UI land together.
/// </summary>
[ComVisible(true)]
[Guid(AddInGuid)]
[ClassInterface(ClassInterfaceType.None)]
[ProgId("SwReview.AddIn.SwReviewAddIn")]
public class SwReviewAddIn : ISwAddin
{
    /// <summary>
    /// The add-in identity. It is written into the HKLM AddIns key above and must never
    /// change once a workstation has registered it.
    /// </summary>
    public const string AddInGuid = "5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55";

    private ISldWorks? _swApp;
    private int _addInCookie;

    /// <summary>The running SOLIDWORKS session, or null while disconnected.</summary>
    public ISldWorks? SwApp => _swApp;

    /// <summary>The callback cookie SOLIDWORKS issued for this add-in instance.</summary>
    public int AddInCookie => _addInCookie;

    /// <summary>
    /// Called by SOLIDWORKS when the add-in loads. Everything the extractor does runs on
    /// this thread, which is the application STA thread (constitution: all COM calls on one
    /// STA thread).
    /// </summary>
    public bool ConnectToSW(object ThisSW, int Cookie)
    {
        _swApp = (ISldWorks)ThisSW;
        _addInCookie = Cookie;

        // Required before any callback can be routed back to this add-in.
        _swApp.SetAddinCallbackInfo2(0, this, _addInCookie);

        // T060: create the Task Pane and its buttons here.
        return true;
    }

    /// <summary>
    /// Called by SOLIDWORKS when the add-in unloads. Release every interop pointer so the
    /// session can shut down cleanly.
    /// </summary>
    public bool DisconnectFromSW()
    {
        // T060: remove the Task Pane and detach its event handlers here.
        _swApp = null;
        _addInCookie = 0;
        return true;
    }
}
