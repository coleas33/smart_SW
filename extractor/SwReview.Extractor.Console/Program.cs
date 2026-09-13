using System;
using System.Runtime.CompilerServices;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using static System.Console;

namespace SwReview.Extractor.Console;

/// <summary>
/// Out-of-process host for the extractor (research R1). Commands and options follow
/// contracts/cli.md; exit code 0 on success, 1 on error, and <c>extract.log</c> is always
/// written next to the output.
///
/// dump and resolve are implemented here (T059). interference and capture arrive with
/// T071, serve with T072; an unimplemented command exits 1 rather than pretending to
/// succeed.
/// </summary>
public static class Program
{
    private const int ExitSuccess = 0;
    private const int ExitError = 1;

    private static readonly string[] DumpOptionNames = { "doc", "config", "out", "meshes", "faces" };

    private static readonly string[] ResolveOptionNames = { "ref", "doc", "out" };

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

        // Must happen before any method that mentions an interop type is CALLED: the JIT
        // loads SolidWorks.Interop.* when it compiles such a method, not when the line runs.
        InteropResolver.Install();

        string command = args[0];
        switch (command)
        {
            case "dump":
                return RunDump(args);

            case "resolve":
                return RunResolve(args);

            case "interference":
            case "capture":
            case "serve":
                Error.WriteLine($"swreview-extract: '{command}' is not implemented yet.");
                Error.WriteLine("  interference, capture   T071    serve   T072");
                return ExitError;

            default:
                Error.WriteLine($"swreview-extract: unknown command '{command}'.");
                Error.WriteLine(string.Empty);
                WriteUsage(Error);
                return ExitError;
        }
    }

    /// <summary>
    /// Parses, then executes. The two are separate methods on purpose: this one mentions no
    /// interop type, so a bad option prints its message and exits 1 even on a machine with
    /// no SOLIDWORKS installed.
    /// </summary>
    private static int RunDump(string[] args)
    {
        CommandLine parsed;
        DumpOptions options;

        try
        {
            parsed = CommandLine.Parse(args, 1, DumpOptionNames);
            options = new DumpOptions
            {
                OutputDirectory = parsed.Required("out"),
                Configuration = parsed.Value("config"),
                Meshes = parsed.MeshFormat(),
                Faces = parsed.FaceScope(),
            };
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract dump: {error.Message}");
            return ExitError;
        }

        return ExecuteDump(options, parsed.Value("doc"));
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteDump(DumpOptions options, string? documentPath)
    {
        using (var log = new ExtractLog(options.OutputDirectory))
        {
            try
            {
                log.Write($"dump --out \"{options.OutputDirectory}\" "
                    + $"--meshes {options.Meshes.ToString().ToLowerInvariant()} "
                    + $"--faces {options.Faces.ToString().ToLowerInvariant()}");

                ISldWorks swApp = SwAttach.Connect(out bool started);
                log.Write(started
                    ? "Started a new SOLIDWORKS session (nothing was running)."
                    : "Attached to the running SOLIDWORKS session.");

                SwSession session = SwSession.Attach(swApp, documentPath, options.Configuration);
                log.Write($"Document: {session.DocumentPath}");
                log.Write($"Configuration: {session.Configuration.Name}");

                DumpResult result = SwDump.CreateWriter(swApp, session).Write(options);

                log.Write($"Wrote {result.PackageFilePath}");
                log.Write($"{result.Package.Components.Count} components, "
                    + $"{result.Package.Holes.Count} holes, "
                    + $"{result.Package.Fasteners.Count} fasteners, "
                    + $"{result.Package.Faces.Count} faces, "
                    + $"{result.Package.Bodies.Count} bodies, "
                    + $"{result.Gaps.Count} gaps");

                Out.WriteLine(result.PackageFilePath);
                return ExitSuccess;
            }
            catch (Exception error)
            {
                log.WriteError("dump failed.", error);
                return ExitError;
            }
        }
    }

    /// <summary>
    /// The round-trip test from quickstart Scenario 2: close and reopen the assembly, then
    /// ask what a reference resolves to. The state code is printed as well as the name,
    /// because "suppressed" and "deleted" mean different things to the reviewer.
    /// </summary>
    private static int RunResolve(string[] args)
    {
        CommandLine parsed;
        string reference;

        try
        {
            parsed = CommandLine.Parse(args, 1, ResolveOptionNames);
            reference = parsed.Required("ref");
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract resolve: {error.Message}");
            return ExitError;
        }

        return ExecuteResolve(reference, parsed.Value("doc"), parsed.Value("out"));
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteResolve(string reference, string? documentPath, string? outputDirectory)
    {
        using (var log = new ExtractLog(outputDirectory))
        {
            try
            {
                ISldWorks swApp = SwAttach.Connect(out bool started);
                log.Write(started
                    ? "Started a new SOLIDWORKS session (nothing was running)."
                    : "Attached to the running SOLIDWORKS session.");

                SwSession session = SwSession.Attach(swApp, documentPath, null);
                var refs = new PersistRefService(session.Gate);

                ResolvedPersistRef resolved = refs.Resolve(session.Document, reference);

                Out.WriteLine($"state: {(int)resolved.State} ({resolved.Describe()})");
                Out.WriteLine($"type: {DescribeType(resolved.Entity)}");
                Out.WriteLine($"name: {DescribeName(resolved.Entity, session)}");

                log.Write($"resolve --ref (len {reference.Length}) -> state {(int)resolved.State}");
                return resolved.IsOk ? ExitSuccess : ExitError;
            }
            catch (Exception error)
            {
                log.WriteError("resolve failed.", error);
                return ExitError;
            }
        }
    }

    /// <summary>What kind of entity came back. Interop hands back RCWs, so this is by interface.</summary>
    private static string DescribeType(object? entity)
    {
        switch (entity)
        {
            case null:
                return "(nothing)";
            case IComponent2 _:
                return "component";
            case IFace2 _:
                return "face";
            case IFeature _:
                return "feature";
            case IBody2 _:
                return "body";
            case IEdge _:
                return "edge";
            default:
                return entity.GetType().Name;
        }
    }

    private static string DescribeName(object? entity, ISwSession session)
    {
        switch (entity)
        {
            case IComponent2 component:
                return session.Gate.Call("Name2", () => component.Name2) ?? "(unnamed)";
            case IFeature feature:
                return session.Gate.Call("Feature.Name", () => feature.Name) ?? "(unnamed)";
            case IBody2 body:
                return session.Gate.Call("Body.Name", () => body.Name) ?? "(unnamed)";
            case IFace2 face:
                var owner = session.Gate.Call("Face.GetBody", () => face.GetBody()) as IBody2;
                return owner == null
                    ? "(face)"
                    : "face of " + (session.Gate.Call("Body.Name", () => owner.Name) ?? "(unnamed body)");
            default:
                return "(no name)";
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
        writer.WriteLine("  resolve       --ref <persist_ref> [--doc <path>] [--out <dir>]");
        writer.WriteLine("                Print what a persistent reference resolves to (round-trip test).");
        writer.WriteLine("  serve         --pipe <name>");
        writer.WriteLine("                Run the read-only bridge: one JSON request per line.");
        writer.WriteLine(string.Empty);
        writer.WriteLine("Exit codes: 0 success, 1 error. extract.log is written next to --out.");
    }
}
