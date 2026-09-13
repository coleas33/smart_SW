using System;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn;

/// <summary>
/// In-process SOLIDWORKS 2024 add-in host (research R1: in-process traversal is 10 to 100x
/// faster than out-of-process COM, and several many-parameter API members fail late-bound).
///
/// It owns the ISldWorks pointer and a Task Pane with three buttons, all acting on the
/// active document: <b>Dump IR</b> runs <see cref="PackageWriter"/> (T060),
/// <b>Interference</b> runs <see cref="InterferenceRunner"/> and <b>Capture selection</b>
/// runs <see cref="CaptureService"/> (T076). The latter two append to the package.json that
/// Dump IR wrote in the same folder, so their results can name its components.
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
            _panel.InterferenceRequested -= OnInterferenceRequested;
            _panel.CaptureRequested -= OnCaptureRequested;
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
        _panel.InterferenceRequested += OnInterferenceRequested;
        _panel.CaptureRequested += OnCaptureRequested;

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
    /// T076. Runs interference detection on the active document with the dialog's default
    /// settings and merges the results into the package.json already in the chosen folder.
    ///
    /// The settings are the defaults on purpose: the Task Pane is for the engineer standing
    /// at the model, and a row of checkboxes here would be a second, quieter place for the
    /// run configuration to differ from the console's. Anyone who needs other settings runs
    /// <c>swreview-extract interference</c>, which echoes them into the IR.
    /// </summary>
    private void OnInterferenceRequested(object sender, string outputDirectory)
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

            EvidencePackage package = PackageAppender.Load(outputDirectory);

            _panel.ShowProgress("Walking the component tree...");
            SwScope scope = SwScope.Open(_swApp, session);

            _panel.ShowProgress($"Detecting interferences in {scope.Components.Count} components...");
            InterferenceRunResult result = new InterferenceRunner(scope.InterferenceSource()).Run(
                session.Configuration.Name,
                new[] { InterferencePair.WholeAssembly() },
                new InterferenceRunSettings(),
                handle => scope.Components.IdOf(handle),
                id => scope.Components.PatternOf(id));

            PackageAppender.Merge(
                package, session.Configuration.Name, result.Interferences, result.Gaps);
            string path = PackageAppender.Save(outputDirectory, package);

            _panel.ShowResult(
                $"{result.Interferences.Count} interference rows and {result.Gaps.Count} gaps "
                + $"appended to{System.Environment.NewLine}{path}");
        }
        catch (Exception error)
        {
            _panel.ShowError("Interference detection did not finish.", error);
        }
        finally
        {
            _panel.SetBusy(false);
        }
    }

    /// <summary>
    /// T076. Captures whatever is selected in SOLIDWORKS right now.
    ///
    /// The selection is the input, so the engineer picks the face or component in the
    /// graphics area and presses the button. Its persistent reference is taken first and
    /// the capture is driven from that reference, which is the same path the console and the
    /// bridge take - so a capture made here is navigable from the report exactly like one
    /// made from a review (Principle IV).
    /// </summary>
    private void OnCaptureRequested(object sender, CaptureRequest request)
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

            object? selected = SelectedEntity(session);
            if (selected == null)
            {
                _panel.ShowResult("Select a face, edge or component in the graphics area first.");
                return;
            }

            EvidencePackage package = PackageAppender.Load(request.OutputDirectory);
            SwScope scope = SwScope.Open(_swApp, session);

            ScopedPersistRef reference = scope.Refs.Get(session.Document, selected);

            _panel.ShowProgress($"Capturing the selection ({request.View})...");
            var captures = new CaptureService(
                scope.CaptureView(), PackageAppender.CaptureIds(package));
            CaptureResult result = captures.Capture(
                reference.Base64, null, request.View, request.OutputDirectory, "Task Pane capture");

            PackageAppender.Merge(package, result.Capture, result.Gap);
            string path = PackageAppender.Save(request.OutputDirectory, package);

            if (!result.Succeeded)
            {
                _panel.ShowResult(
                    $"No image: {result.Gap!.Reason}."
                    + $"{System.Environment.NewLine}The gap was appended to {path}.");
                return;
            }

            _panel.ShowResult(
                $"Wrote {result.Capture!.File}"
                + $"{System.Environment.NewLine}and appended {result.Capture.Id} to {path}");
        }
        catch (Exception error)
        {
            _panel.ShowError("The capture did not finish.", error);
        }
        finally
        {
            _panel.SetBusy(false);
        }
    }

    /// <summary>The first selected object, or null when nothing is selected.</summary>
    private static object? SelectedEntity(ISwSession session)
    {
        var selection = session.Gate.Call(
            "SelectionManager", () => session.Document.SelectionManager) as ISelectionMgr;

        if (selection == null)
        {
            return null;
        }

        int count = session.Gate.Call(
            "GetSelectedObjectCount2", () => selection.GetSelectedObjectCount2(-1));

        if (count < 1)
        {
            return null;
        }

        // 1-based, and -1 means "in any configuration".
        return session.Gate.Call("GetSelectedObject6", () => selection.GetSelectedObject6(1, -1));
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
