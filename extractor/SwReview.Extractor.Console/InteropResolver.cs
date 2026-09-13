using System;
using System.IO;
using System.Reflection;
using Microsoft.Win32;

namespace SwReview.Extractor.Console;

/// <summary>
/// Finds the SOLIDWORKS interop assemblies at run time.
///
/// They are referenced with <c>Private=false</c> so the build does not copy them (the
/// add-in and this host must share ONE set of interop types with the SOLIDWORKS process),
/// and SOLIDWORKS 2024 does not install them to the GAC. Out of process, nothing would
/// resolve them, so this handler probes the seat's redist folder - the same folder the
/// build referenced.
///
/// Install it before any method that mentions an interop type is called: the JIT loads the
/// assembly when it compiles that method, not when the line runs.
/// </summary>
public static class InteropResolver
{
    private const string InteropPrefix = "SolidWorks.Interop.";

    private const string DefaultRedist =
        @"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist";

    private static string? _redistFolder;

    /// <summary>Hooks AssemblyResolve. Safe to call more than once.</summary>
    public static void Install(string? redistOverride = null)
    {
        _redistFolder = redistOverride ?? FindRedistFolder();
        AppDomain.CurrentDomain.AssemblyResolve -= Resolve;
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
    }

    /// <summary>Where the interops will be loaded from, for the log.</summary>
    public static string? RedistFolder => _redistFolder;

    private static Assembly? Resolve(object sender, ResolveEventArgs args)
    {
        if (_redistFolder == null || !args.Name.StartsWith(InteropPrefix, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        string simpleName = new AssemblyName(args.Name).Name;
        string path = Path.Combine(_redistFolder, simpleName + ".dll");

        return File.Exists(path) ? Assembly.LoadFrom(path) : null;
    }

    /// <summary>
    /// The seat's api\redist folder, from the SOLIDWORKS install registry key, falling back
    /// to the default install path. SWREVIEW_SW_REDIST overrides both, for a seat installed
    /// somewhere else.
    /// </summary>
    private static string? FindRedistFolder()
    {
        string? fromEnvironment = Environment.GetEnvironmentVariable("SWREVIEW_SW_REDIST");
        if (!string.IsNullOrWhiteSpace(fromEnvironment) && Directory.Exists(fromEnvironment))
        {
            return fromEnvironment;
        }

        string? installed = FromRegistry();
        if (installed != null)
        {
            string redist = Path.Combine(installed, "api", "redist");
            if (Directory.Exists(redist))
            {
                return redist;
            }
        }

        return Directory.Exists(DefaultRedist) ? DefaultRedist : null;
    }

    private static string? FromRegistry()
    {
        // The key is per major release; 2024 is the pilot workstation's version.
        using (RegistryKey? key = Registry.LocalMachine.OpenSubKey(
            @"SOFTWARE\SolidWorks\SOLIDWORKS 2024\Setup"))
        {
            return key?.GetValue("SolidWorks Folder") as string;
        }
    }
}
