using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.CompilerServices;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Console.Serve;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using static System.Console;
using IrCapture = SwReview.Extractor.Ir.Capture;
using IrInterference = SwReview.Extractor.Ir.Interference;

// The five option lists and KnownOptions are the shipped definition of what each
// command accepts; the tests assert against THEM rather than against copies, which
// would pass with the real lists untouched.
[assembly: InternalsVisibleTo("SwReview.Extractor.Tests")]

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

    internal static readonly string[] DumpOptionNames = { "doc", "config", "out", "meshes", "faces" };

    internal static readonly string[] ResolveOptionNames = { "ref", "doc", "out" };

    internal static readonly string[] InterferenceOptionNames =
    {
        "config", "pairs", "coincident-as-interference", "subassemblies-as-components",
        "include-multibody", "ignore-hidden", "fasteners", "out", "truncate-after",
    };

    internal static readonly string[] CaptureOptionNames = { "ref", "doc", "view", "out", "note" };

    internal static readonly string[] ServeOptionNames = { "pipe", "doc", "config", "out" };

    /// <summary>
    /// Every command attaches, so every command accepts <c>--allow-start</c>. It is added
    /// here rather than repeated in all five lists, where one omission would make the flag
    /// a usage error on exactly one command.
    /// </summary>
    internal static string[] KnownOptions(string[] commandOptions)
    {
        var known = new List<string>(commandOptions) { "allow-start" };
        return known.ToArray();
    }

    /// <summary>
    /// Attaches and says which happened. Shared by all five commands so the wording - and
    /// the attach-only default - cannot drift between them.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static ISldWorks Connect(bool allowStart, ExtractLog log)
    {
        ISldWorks swApp = SwAttach.Connect(allowStart, out bool started, out string? diagnosis);
        if (!started)
        {
            log.Write("Attached to the running SOLIDWORKS session.");
            return swApp;
        }

        // The log must not say "nothing was running": all that is known is that the running
        // object table lookup failed, and the diagnosis below is printed precisely when an
        // SLDWORKS.exe WAS running that COM could not see (constitution, Principle I).
        if (diagnosis != null)
        {
            log.Write(diagnosis);
        }

        log.Write("Attach failed and --allow-start was given, so a SOLIDWORKS session was "
            + "requested (it has none of your open documents).");

        return swApp;
    }

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
                return RunInterference(args);

            case "capture":
                return RunCapture(args);

            case "serve":
                return RunServe(args);

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
        bool allowStart;

        try
        {
            parsed = CommandLine.Parse(args, 1, KnownOptions(DumpOptionNames));
            allowStart = parsed.Flag("allow-start");
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

        return ExecuteDump(options, parsed.Value("doc"), allowStart);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteDump(DumpOptions options, string? documentPath, bool allowStart)
    {
        using (var log = new ExtractLog(options.OutputDirectory))
        {
            try
            {
                log.Write($"dump --out \"{options.OutputDirectory}\" "
                    + $"--meshes {options.Meshes.ToString().ToLowerInvariant()} "
                    + $"--faces {options.Faces.ToString().ToLowerInvariant()}");

                ISldWorks swApp = Connect(allowStart, log);

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
        bool allowStart;

        try
        {
            parsed = CommandLine.Parse(args, 1, KnownOptions(ResolveOptionNames));
            allowStart = parsed.Flag("allow-start");
            reference = parsed.Required("ref");
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract resolve: {error.Message}");
            return ExitError;
        }

        return ExecuteResolve(reference, parsed.Value("doc"), parsed.Value("out"), allowStart);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteResolve(
        string reference, string? documentPath, string? outputDirectory, bool allowStart)
    {
        using (var log = new ExtractLog(outputDirectory))
        {
            try
            {
                ISldWorks swApp = Connect(allowStart, log);

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

    /// <summary>
    /// T071. Runs interference detection and merges the results into the package.json that
    /// <c>dump</c> already wrote in <c>--out</c>, so the results sit next to the components
    /// they name (contracts/cli.md).
    /// </summary>
    private static int RunInterference(string[] args)
    {
        CommandLine parsed;
        string outputDirectory;
        InterferenceRunSettings settings;
        IReadOnlyList<string[]> namedPairs;
        int? truncateAfter;
        bool allowStart;

        try
        {
            parsed = CommandLine.Parse(args, 1, KnownOptions(InterferenceOptionNames));
            allowStart = parsed.Flag("allow-start");
            outputDirectory = parsed.Required("out");
            namedPairs = parsed.Pairs();
            truncateAfter = parsed.Int("truncate-after");
            settings = new InterferenceRunSettings
            {
                TreatCoincidentAsInterference = parsed.Flag("coincident-as-interference"),
                TreatSubassembliesAsComponents = parsed.Flag("subassemblies-as-components"),
                IncludeMultibody = parsed.Flag("include-multibody"),
                IgnoreHidden = parsed.Flag("ignore-hidden"),
                Fasteners = parsed.FastenerTreatment(),
            };
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract interference: {error.Message}");
            return ExitError;
        }

        return ExecuteInterference(
            outputDirectory, parsed.Value("config"), namedPairs, settings, truncateAfter, allowStart);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteInterference(
        string outputDirectory,
        string? configuration,
        IReadOnlyList<string[]> namedPairs,
        InterferenceRunSettings settings,
        int? truncateAfter,
        bool allowStart)
    {
        using (var log = new ExtractLog(outputDirectory))
        {
            try
            {
                log.Write($"interference --out \"{outputDirectory}\" "
                    + $"--pairs {(namedPairs.Count == 0 ? "all" : namedPairs.Count + " pair(s)")} "
                    + $"--fasteners {PackageSerializer.EnumToJsonName(settings.Fasteners)}");

                // Loaded before SOLIDWORKS is touched: a missing package is a usage mistake,
                // and finding that out after a two-second attach helps nobody.
                EvidencePackage package = PackageAppender.Load(outputDirectory);

                ISldWorks swApp = Connect(allowStart, log);

                SwSession session = SwSession.Attach(swApp, null, configuration);
                SwScope scope = SwScope.Open(swApp, session);
                log.Write($"Document: {session.DocumentPath} [{session.Configuration.Name}], "
                    + $"{scope.Components.Count} components");

                List<InterferencePair> pairs = BuildPairs(scope, namedPairs);

                InterferenceRunResult result = new InterferenceRunner(scope.InterferenceSource()).Run(
                    session.Configuration.Name,
                    pairs,
                    settings,
                    handle => scope.Components.IdOf(handle),
                    id => scope.Components.PatternOf(id),
                    truncateAfter);

                PackageAppender.Merge(
                    package, session.Configuration.Name, result.Interferences, result.Gaps);
                string path = PackageAppender.Save(outputDirectory, package);

                int computed = 0;
                int truncated = 0;
                int failed = 0;
                foreach (IrInterference row in result.Interferences)
                {
                    if (row.Status == InterferenceStatus.Computed)
                    {
                        computed++;
                    }
                    else if (row.Status == InterferenceStatus.Truncated)
                    {
                        truncated++;
                    }
                    else
                    {
                        failed++;
                    }
                }

                log.Write($"{computed} computed, {truncated} truncated, {failed} failed, "
                    + $"{result.Gaps.Count} gaps -> {path}");

                Out.WriteLine(path);
                return ExitSuccess;
            }
            catch (Exception error)
            {
                log.WriteError("interference failed.", error);
                return ExitError;
            }
        }
    }

    /// <summary>
    /// <c>--pairs all</c> is one whole-assembly unit of work; named pairs are resolved
    /// against the live tree, and an id this document does not have is refused by name
    /// rather than skipped - skipping it would report no interference for a pair that was
    /// never checked (Principle I).
    /// </summary>
    private static List<InterferencePair> BuildPairs(SwScope scope, IReadOnlyList<string[]> namedPairs)
    {
        var pairs = new List<InterferencePair>();
        if (namedPairs.Count == 0)
        {
            pairs.Add(InterferencePair.WholeAssembly());
            return pairs;
        }

        foreach (string[] ids in namedPairs)
        {
            InterferenceComponent? first = scope.Components.ById(ids[0]);
            InterferenceComponent? second = scope.Components.ById(ids[1]);

            if (first == null || second == null)
            {
                throw new InvalidOperationException(
                    $"'{(first == null ? ids[0] : ids[1])}' is not a component of this assembly. "
                    + "Component ids come from the package.json that dump wrote for this document "
                    + "and this configuration.");
            }

            pairs.Add(InterferencePair.Of(first, second));
        }

        return pairs;
    }

    /// <summary>
    /// T071. Frames one entity and saves a PNG under <c>--out</c>/<c>captures</c>, then
    /// appends the <c>Capture</c> row to the package.
    /// </summary>
    private static int RunCapture(string[] args)
    {
        CommandLine parsed;
        string reference;
        string outputDirectory;
        string view;
        bool allowStart;

        try
        {
            parsed = CommandLine.Parse(args, 1, KnownOptions(CaptureOptionNames));
            allowStart = parsed.Flag("allow-start");
            reference = parsed.Required("ref");
            outputDirectory = parsed.Required("out");
            view = parsed.CaptureView();
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract capture: {error.Message}");
            return ExitError;
        }

        return ExecuteCapture(
            reference,
            parsed.Value("doc"),
            view,
            outputDirectory,
            parsed.Value("note") ?? string.Empty,
            allowStart);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteCapture(
        string reference,
        string? documentPath,
        string view,
        string outputDirectory,
        string note,
        bool allowStart)
    {
        using (var log = new ExtractLog(outputDirectory))
        {
            try
            {
                log.Write($"capture --view {view} --out \"{outputDirectory}\"");

                EvidencePackage package = PackageAppender.Load(outputDirectory);

                ISldWorks swApp = Connect(allowStart, log);

                SwSession session = SwSession.Attach(swApp, documentPath, null);
                SwScope scope = SwScope.Open(swApp, session);

                var captures = new CaptureService(scope.CaptureView(), PackageAppender.CaptureIds(package));
                CaptureResult result = captures.Capture(
                    reference, documentPath, view, outputDirectory, note);

                PackageAppender.Merge(package, result.Capture, result.Gap);
                string path = PackageAppender.Save(outputDirectory, package);

                if (!result.Succeeded)
                {
                    log.Write($"No image: {result.Gap!.Reason} ({result.Gap.Error})");
                    log.Write($"Gap appended to {path}");
                    return ExitError;
                }

                log.Write($"Wrote {result.Capture!.File} and appended {result.Capture.Id} to {path}");
                Out.WriteLine(Path.Combine(outputDirectory, result.Capture.File.Replace('/', Path.DirectorySeparatorChar)));
                return ExitSuccess;
            }
            catch (Exception error)
            {
                log.WriteError("capture failed.", error);
                return ExitError;
            }
        }
    }

    /// <summary>
    /// T072. Runs the read-only bridge until Ctrl+C: one JSON request per line on a named
    /// pipe, one STA worker thread owning the SldWorks pointer. The wire format is
    /// Serve/PROTOCOL.md.
    /// </summary>
    private static int RunServe(string[] args)
    {
        CommandLine parsed;
        string pipeName;
        bool allowStart;

        try
        {
            parsed = CommandLine.Parse(args, 1, KnownOptions(ServeOptionNames));
            allowStart = parsed.Flag("allow-start");
            pipeName = parsed.Required("pipe");
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract serve: {error.Message}");
            return ExitError;
        }

        return ExecuteServe(
            pipeName, parsed.Value("doc"), parsed.Value("config"), parsed.Value("out"), allowStart);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteServe(
        string pipeName,
        string? documentPath,
        string? configuration,
        string? outputDirectory,
        bool allowStart)
    {
        // Captures need somewhere to go, and the client never names a path (research R4).
        string captureDirectory = string.IsNullOrWhiteSpace(outputDirectory)
            ? Path.Combine(Path.GetTempPath(), "swreview-bridge", SafeName(pipeName))
            : outputDirectory!;

        using (var log = new ExtractLog(outputDirectory))
        {
            using (var stopping = new CancellationTokenSource())
            {
                CancelKeyPress += (sender, e) =>
                {
                    // Ctrl+C stops the accept loop rather than killing the process mid-call,
                    // so the STA worker finishes the request it is on.
                    e.Cancel = true;
                    stopping.Cancel();
                };

                try
                {
                    log.Write($"serve --pipe {pipeName}");
                    log.Write($"Captures go to {captureDirectory}");

                    using (var server = new PipeServer(
                        pipeName,
                        () => BuildDispatcher(
                            documentPath, configuration, captureDirectory, allowStart, log),
                        System.Console.Error))
                    {
                        log.Write($@"Listening on \\.\pipe\{pipeName}. Ctrl+C to stop.");
                        server.Run(stopping.Token);
                    }

                    log.Write("serve stopped.");
                    return ExitSuccess;
                }
                catch (Exception error)
                {
                    log.WriteError("serve failed.", error);
                    return ExitError;
                }
            }
        }
    }

    /// <summary>
    /// Runs ON the STA worker thread (see <see cref="PipeServer"/>): every COM pointer below
    /// is created there and never leaves it.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static IBridgeDispatcher BuildDispatcher(
        string? documentPath,
        string? configuration,
        string captureDirectory,
        bool allowStart,
        ExtractLog log)
    {
        ISldWorks swApp = Connect(allowStart, log);

        SwSession session = SwSession.Attach(swApp, documentPath, configuration);
        SwScope scope = SwScope.Open(swApp, session);
        log.Write($"Bridge attached to {session.DocumentPath} [{session.Configuration.Name}], "
            + $"{scope.Components.Count} components");

        var services = new BridgeServices(
            scope.CaptureView(),
            scope.MeasureSource(),
            scope.InterferenceSource(),
            scope.Components,
            captureDirectory)
        {
            SwVersion = session.SwVersion,
            DocumentPath = session.DocumentPath,
            Configuration = session.Configuration.Name,
        };

        // The console host issues no secret: its boundary is the named pipe an engineer
        // started at this workstation. The add-in's in-process host is the one that scopes
        // commands by secret (T045).
        return new SwBridgeDispatcher(services, NoSecretPolicy.Instance);
    }

    /// <summary>A pipe name is user input and ends up in a path; strip anything a path cannot hold.</summary>
    private static string SafeName(string pipeName)
    {
        var safe = new System.Text.StringBuilder(pipeName.Length);
        foreach (char c in pipeName)
        {
            safe.Append(char.IsLetterOrDigit(c) || c == '-' || c == '_' ? c : '_');
        }

        return safe.Length == 0 ? "bridge" : safe.ToString();
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
        writer.WriteLine("                --include-multibody --ignore-hidden");
        writer.WriteLine("                --fasteners include|exclude|only --truncate-after <n>");
        writer.WriteLine("                Append interference results to the package.json in --out.");
        writer.WriteLine("  capture       --ref <persist_ref> [--doc <path>] --out <dir>");
        writer.WriteLine("                --view iso|front|top|right|fit [--note <text>]");
        writer.WriteLine("                Zoom to the entity, save a PNG, append a Capture.");
        writer.WriteLine("  resolve       --ref <persist_ref> [--doc <path>] [--out <dir>]");
        writer.WriteLine("                Print what a persistent reference resolves to (round-trip test).");
        writer.WriteLine("  serve         --pipe <name> [--doc <path>] [--config <name>] [--out <dir>]");
        writer.WriteLine("                Run the read-only bridge: one JSON request per line.");
        writer.WriteLine("                Wire format: Serve/PROTOCOL.md.");
        writer.WriteLine(string.Empty);
        writer.WriteLine("Every command attaches to the running SOLIDWORKS and does not start one:");
        writer.WriteLine("  --allow-start  Start a SOLIDWORKS session if none is running. Off by default:");
        writer.WriteLine("                 a started session holds a licence and has none of your");
        writer.WriteLine("                 open documents, so it would describe a different model.");
        writer.WriteLine(string.Empty);
        writer.WriteLine("Exit codes: 0 success, 1 error. extract.log is written next to --out.");
    }
}
