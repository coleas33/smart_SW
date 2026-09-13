using System;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn;

/// <summary>
/// In-process SOLIDWORKS 2024 add-in host (research R1: in-process traversal is 10 to 100x
/// faster than out-of-process COM, and several many-parameter API members fail late-bound).
///
/// It owns the ISldWorks pointer and a Task Pane with a <b>Dump IR</b> button that runs
/// <see cref="PackageWriter"/> on the active document (T060). Interference and Capture
/// buttons arrive with T076.
///
/// Registration (research R12, "Add-in hosting"). Both steps need an elevated x64 prompt;
/// the registry keys are written by the [ComRegisterFunction] below, so step 1 does both:
///
///   1. "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\regasm.exe" /codebase SwReview.AddIn.dll
///   2. Enable it for the current user (SOLIDWORKS writes this itself the first time the
///      add-in is ticked in Tools > Add-ins):
///        HKCU\SOFTWARE\SOLIDWORKS\AddInsStartup\{5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55} = 1
///
/// Build x64 and reference the interops from the seat install
/// (C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist) with Embed Interop Types
/// false; the NuGet SolidWorks.Interop packages are community published and are not used.
/// </summary>
[ComVisible(true)]
[Guid(AddInGuid)]
[ClassInterface(ClassInterfaceType.None)]
[ProgId("SwReview.AddIn.SwReviewAddIn")]
public class SwReviewAddIn : ISwAddin
{
    /// <summary>
    /// The add-in identity. It is written into the HKLM AddIns key and must never change
    /// once a workstation has registered it.
    /// </summary>
    public const string AddInGuid = "5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55";

    private const string AddInTitle = "SwReview";

    private const string AddInDescription = "SwReview evidence extractor (read-only)";

    private ISldWorks? _swApp;
    private int _addInCookie;
    private ITaskpaneView? _taskPane;
    private DumpIrPanel? _panel;

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

        CreateTaskPane();
        return true;
    }

    /// <summary>
    /// Called by SOLIDWORKS when the add-in unloads. Release every interop pointer so the
    /// session can shut down cleanly.
    /// </summary>
    public bool DisconnectFromSW()
    {
        if (_panel != null)
        {
            _panel.DumpRequested -= OnDumpRequested;
            _panel.Dispose();
            _panel = null;
        }

        if (_taskPane != null)
        {
            _taskPane.DeleteView();
            Marshal.ReleaseComObject(_taskPane);
            _taskPane = null;
        }

        _swApp = null;
        _addInCookie = 0;

        GC.Collect();
        GC.WaitForPendingFinalizers();
        return true;
    }

    private void CreateTaskPane()
    {
        if (_swApp == null)
        {
            return;
        }

        _taskPane = _swApp.CreateTaskpaneView2(string.Empty, AddInDescription);
        if (_taskPane == null)
        {
            return;
        }

        _panel = new DumpIrPanel();
        _panel.DumpRequested += OnDumpRequested;

        // x64 build, so the 64-bit handle overload is the correct one; the Int32 version
        // truncates the window handle and silently shows nothing.
        _taskPane.DisplayWindowFromHandlex64(_panel.Handle.ToInt64());
    }

    /// <summary>
    /// Runs the dump on the active document. The panel is told what is happening before and
    /// after; a failure shows the exception rather than leaving a half-written package with
    /// no explanation (constitution Principle I).
    /// </summary>
    private void OnDumpRequested(object sender, string outputDirectory)
    {
        if (_swApp == null || _panel == null)
        {
            return;
        }

        _panel.SetBusy(true);
        try
        {
            _panel.ShowProgress("Attaching to the active document...");

            SwSession session = SwSession.Attach(_swApp, documentPath: null, configurationName: null);

            _panel.ShowProgress(
                $"Dumping {System.IO.Path.GetFileName(session.DocumentPath)} "
                + $"[{session.Configuration.Name}]...");

            var options = new DumpOptions
            {
                OutputDirectory = outputDirectory,
                Configuration = session.Configuration.Name,
                Meshes = MeshFormat.Glb,
                Faces = FaceScope.Needed,
            };

            DumpResult result = SwDump.CreateWriter(_swApp, session).Write(options);

            _panel.ShowResult(
                $"Wrote {result.Package.Components.Count} components, "
                + $"{result.Package.Holes.Count} holes, "
                + $"{result.Package.Fasteners.Count} fasteners and "
                + $"{result.Gaps.Count} gaps to{System.Environment.NewLine}{result.PackageFilePath}");
        }
        catch (Exception error)
        {
            _panel.ShowError("The dump did not finish.", error);
        }
        finally
        {
            _panel.SetBusy(false);
        }
    }

    /// <summary>
    /// Written by regasm /codebase. SOLIDWORKS reads these keys at startup to find the
    /// add-in; without them the COM class is registered but never loaded.
    /// </summary>
    [ComRegisterFunction]
    public static void RegisterFunction(Type type)
    {
        using (RegistryKey key = Registry.LocalMachine.CreateSubKey(AddInKeyPath))
        {
            key.SetValue(null, 1, RegistryValueKind.DWord);       // load at startup
            key.SetValue("Description", AddInDescription, RegistryValueKind.String);
            key.SetValue("Title", AddInTitle, RegistryValueKind.String);
        }

        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(StartupKeyPath))
        {
            key.SetValue(null, 1, RegistryValueKind.DWord);       // enabled for this user
        }
    }

    /// <summary>Written by regasm /unregister. Leaves nothing behind.</summary>
    [ComUnregisterFunction]
    public static void UnregisterFunction(Type type)
    {
        Registry.LocalMachine.DeleteSubKeyTree(AddInKeyPath, throwOnMissingSubKey: false);
        Registry.CurrentUser.DeleteSubKeyTree(StartupKeyPath, throwOnMissingSubKey: false);
    }

    private static string AddInKeyPath => @"SOFTWARE\SOLIDWORKS\AddIns\{" + AddInGuid + "}";

    private static string StartupKeyPath => @"SOFTWARE\SOLIDWORKS\AddInsStartup\{" + AddInGuid + "}";
}
