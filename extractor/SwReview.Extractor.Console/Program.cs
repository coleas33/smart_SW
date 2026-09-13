using System;
using static System.Console;

namespace SwReview.Extractor.Console;

/// <summary>
/// Out-of-process host for the extractor (research R1). Commands and options follow
/// contracts/cli.md; exit code 0 on success, 1 on error.
///
/// T004 skeleton: the command name is parsed and usage is printed. The commands themselves
/// arrive with their phases - dump and resolve in T059, interference and capture in T071,
/// serve in T072 - so an unimplemented command exits 1 rather than pretending to succeed.
/// </summary>
public static class Program
{
    private const int ExitSuccess = 0;
    private const int ExitError = 1;

    /// <summary>
    /// STA is mandatory: every SOLIDWORKS COM call in this process must run on one STA
    /// thread (constitution, Technical Constraints).
    /// </summary>
    [STAThread]
    public static int Main(string[] args)
    {
        if (args.Length == 0 || IsHelpFlag(args[0]))
        {
            WriteUsage(Out);
            return ExitSuccess;
        }

        string command = args[0];
        switch (command)
        {
            case "dump":
            case "interference":
            case "capture":
            case "resolve":
            case "serve":
                Error.WriteLine($"swreview-extract: '{command}' is not implemented yet.");
                Error.WriteLine("  dump, resolve      T059    interference, capture   T071    serve   T072");
                return ExitError;

            default:
                Error.WriteLine($"swreview-extract: unknown command '{command}'.");
                Error.WriteLine(string.Empty);
                WriteUsage(Error);
                return ExitError;
        }
    }

    private static bool IsHelpFlag(string arg) =>
        arg == "-h" || arg == "--help" || arg == "help" || arg == "/?";

    private static void WriteUsage(System.IO.TextWriter writer)
    {
        writer.WriteLine("swreview-extract - SOLIDWORKS evidence extractor (read-only)");
        writer.WriteLine(string.Empty);
        writer.WriteLine("Usage: swreview-extract <command> [options]");
        writer.WriteLine(string.Empty);
        writer.WriteLine("Commands:");
        writer.WriteLine("  dump          --doc <path> --config <name> --out <dir>");
        writer.WriteLine("                --meshes glb|stl|none --faces needed|all");
        writer.WriteLine("                Write package.json and meshes/ for the active or named document.");
        writer.WriteLine("  interference  --config <name> --pairs all|<id,id>... --out <dir>");
        writer.WriteLine("                --coincident-as-interference --subassemblies-as-components");
        writer.WriteLine("                --fasteners include|exclude|only --truncate-after <n>");
        writer.WriteLine("                Append interference results to package.json.");
        writer.WriteLine("  capture       --ref <persist_ref> --view iso|front|top|right|fit --out <dir>");
        writer.WriteLine("                Zoom to the entity and save a PNG.");
        writer.WriteLine("  resolve       --ref <persist_ref>");
        writer.WriteLine("                Print what a persistent reference resolves to (round-trip test).");
        writer.WriteLine("  serve         --pipe <name>");
        writer.WriteLine("                Run the read-only bridge: one JSON request per line.");
        writer.WriteLine(string.Empty);
        writer.WriteLine("Exit codes: 0 success, 1 error.");
    }
}
