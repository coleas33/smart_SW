using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using SwReview.Extractor.Rms;

namespace SwReview.Extractor.Console;

/// <summary>
/// 004 T181 (default taken 2026-09-27, the owner may revise; research R15.1):
/// <c>swreview-extract probe interop --emit-manifest &lt;path&gt; [--force]</c>. Writes the frozen
/// interop-surface manifest from the committed selection (<see cref="RemodelInteropSurface"/>) and
/// the installed interop assemblies' metadata (<see cref="RemodelInteropManifest"/>), so the rows
/// are regenerated and never typed.
///
/// It addresses no document and no session: SOLIDWORKS is neither attached to nor started, no COM
/// object is created, and the assemblies are read for their types and methods only. It writes
/// nothing, and exits 1, when the path is missing, is a folder, or exists without
/// <c>--force</c> (the re-modeler's copy refuses to overwrite for the same reason); when no redist
/// folder holds both assemblies; and when the generation found any problem, each of which it prints.
/// </summary>
internal static class InteropManifestProbe
{
    private const int ExitSuccess = 0;
    private const int ExitError = 1;

    private const string Prefix = "swreview-extract probe interop: ";

    /// <summary>
    /// Runs the command. <paramref name="redistFolder"/> is the seat's <c>api\redist</c> folder,
    /// as <see cref="InteropResolver"/> found it; <paramref name="generatedAtUtc"/> is the second the
    /// manifest records.
    /// </summary>
    public static int Run(
        string? emitPath,
        bool force,
        string? redistFolder,
        DateTime generatedAtUtc,
        TextWriter output,
        TextWriter error)
    {
        if (output == null)
        {
            throw new ArgumentNullException(nameof(output));
        }

        if (error == null)
        {
            throw new ArgumentNullException(nameof(error));
        }

        if (string.IsNullOrWhiteSpace(emitPath))
        {
            error.WriteLine(Prefix + "--emit-manifest <path> names the file to write, and is required.");
            return ExitError;
        }

        string path;
        try
        {
            path = Path.GetFullPath(emitPath!.Trim());
        }
        catch (Exception failure) when (failure is ArgumentException || failure is NotSupportedException || failure is PathTooLongException)
        {
            error.WriteLine(Prefix + "'" + emitPath + "' is not a path a file can have: " + failure.Message);
            return ExitError;
        }

        if (Directory.Exists(path))
        {
            error.WriteLine(Prefix + "'" + path + "' is a folder; --emit-manifest names the file to write.");
            return ExitError;
        }

        if (File.Exists(path) && !force)
        {
            error.WriteLine(
                Prefix + "'" + path + "' already exists and was left as it is. Regenerating the manifest is a "
                + "deliberate, reviewed change: give --force to write over it.");
            return ExitError;
        }

        RemodelInteropAssemblies? interop;
        try
        {
            interop = RemodelInteropAssemblies.FromRedist(redistFolder);
        }
        catch (Exception failure) when (failure is BadImageFormatException || failure is FileLoadException || failure is IOException)
        {
            error.WriteLine(
                Prefix + "the SOLIDWORKS interop assemblies in " + redistFolder + " could not be read: "
                + failure.GetType().Name + ": " + failure.Message);
            return ExitError;
        }

        if (interop == null)
        {
            error.WriteLine(
                Prefix + "the SOLIDWORKS interop assemblies were not found ("
                + (string.IsNullOrWhiteSpace(redistFolder) ? "no api\\redist folder was found" : "looked in " + redistFolder)
                + "); set SWREVIEW_SW_REDIST to the folder that holds "
                + RemodelInteropAssemblies.SldWorksName + ".dll and " + RemodelInteropAssemblies.SwConstName + ".dll.");
            return ExitError;
        }

        RemodelInteropGeneration generation = RemodelInteropManifest.Generate(interop, generatedAtUtc);
        RemodelInteropManifestDocument document = generation.Document;
        if (!generation.Succeeded)
        {
            error.WriteLine(
                Prefix + "nothing was written: " + RemodelInteropAssemblies.SldWorksName + " "
                + document.AssemblyVersion + " (" + redistFolder + ") differs from what the re-modeler records.");
            foreach (string problem in generation.Problems)
            {
                error.WriteLine("  " + problem);
            }

            return ExitError;
        }

        try
        {
            string? folder = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(folder))
            {
                Directory.CreateDirectory(folder);
            }

            File.WriteAllText(path, RemodelInteropManifest.Write(document), new UTF8Encoding(false));
        }
        catch (Exception failure) when (failure is IOException || failure is UnauthorizedAccessException)
        {
            error.WriteLine(Prefix + "'" + path + "' could not be written: " + failure.Message);
            return ExitError;
        }

        output.WriteLine(
            "wrote " + path + ": "
            + Count(document.Members.Count, "member") + ", "
            + Count(document.Enums.Sum(e => e.Values.Count), "enum constant") + " and "
            + Count(document.Absences.Count, "absence") + ", from "
            + RemodelInteropAssemblies.SldWorksName + " " + document.AssemblyVersion + " and "
            + RemodelInteropAssemblies.SwConstName + " " + document.SwconstVersion + " ("
            + document.Product + ") in " + redistFolder + ".");
        return ExitSuccess;
    }

    private static string Count(int count, string noun) =>
        count.ToString(CultureInfo.InvariantCulture) + " " + noun + (count == 1 ? string.Empty : "s");
}
