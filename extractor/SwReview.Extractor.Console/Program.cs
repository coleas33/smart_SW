using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.CompilerServices;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Console.Serve;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using static System.Console;
using IrCapture = SwReview.Extractor.Ir.Capture;
using IrInterference = SwReview.Extractor.Ir.Interference;
using IrMate = SwReview.Extractor.Ir.Mate;

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

    internal static readonly string[] DumpOptionNames =
        { "doc", "config", "out", "meshes", "faces", "features" };

    internal static readonly string[] ResolveOptionNames = { "ref", "doc", "out" };

    internal static readonly string[] InterferenceOptionNames =
    {
        "config", "pairs", "coincident-as-interference", "subassemblies-as-components",
        "include-multibody", "ignore-hidden", "fasteners", "out", "truncate-after",
    };

    internal static readonly string[] CaptureOptionNames = { "ref", "doc", "view", "out", "note" };

    internal static readonly string[] ServeOptionNames = { "pipe", "doc", "config", "out" };

    /// <summary>
    /// <c>probe rms</c> reads one open document and prints; it writes nothing, so it has no
    /// <c>--out</c> and none of the dump options (contracts/cli.md).
    /// </summary>
    internal static readonly string[] ProbeOptionNames = { "doc" };

    /// <summary>The only subject <c>probe</c> accepts today.</summary>
    private const string RmsProbe = "rms";

    /// <summary>
    /// The interop members <c>probe rms</c> reads per feature, by the name each is gated
    /// under - the same names <c>FeatureDumper</c> uses, so the probe's observed member set
    /// is the dump's. <c>SwFeatureReader</c> leaves its single-call members ungated on
    /// purpose (the caller names them so the fake path records the production names), which
    /// on this path makes the probe the caller: ungated they would reach no
    /// <c>ReadOnlyGuard.Assert</c>, no circuit breaker and no SC-004 observer, and
    /// contracts/cli.md says this command uses the read-only guard.
    /// </summary>
    internal static readonly string[] ProbeInteropMembers =
    {
        ProbeMember.Children,
        ProbeMember.Parents,
        ProbeMember.Suppressed,
        ProbeMember.ErrorCode,
        ProbeMember.Description,
        ProbeMember.Sketch,
        ProbeMember.SketchStatus,
        ProbeMember.Definition,
        ProbeMember.Radius,
    };

    /// <summary>Named once so the call sites below and the list above cannot drift apart.</summary>
    private static class ProbeMember
    {
        public const string Children = "GetChildren";
        public const string Parents = "GetParents";
        public const string Suppressed = "IsSuppressed2";
        public const string ErrorCode = "GetErrorCode2";
        public const string Description = "Description";
        public const string Sketch = "GetSpecificFeature2";
        public const string SketchStatus = "GetConstrainedStatus";
        public const string Definition = "GetDefinition";
        public const string Radius = "DefaultRadius";
    }

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

            case "probe":
                return RunProbe(args);

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
                Features = parsed.FeatureScope(),
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
                    + $"--faces {options.Faces.ToString().ToLowerInvariant()} "
                    + $"--features {options.Features.ToString().ToLowerInvariant()}");

                ISldWorks swApp = Connect(allowStart, log);

                SwSession session = SwSession.Attach(swApp, documentPath, options.Configuration);
                log.Write($"Document: {session.DocumentPath}");
                log.Write($"Configuration: {session.Configuration.Name}");

                DumpResult result = SwDump.CreateWriter(swApp, session).Write(options);

                log.Write($"Wrote {result.PackageFilePath}");
                log.Write($"{result.Package.Components.Count} components, "
                    + $"{result.Package.Features.Count} features, "
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

    /// <summary>
    /// T031. <c>probe rms --doc &lt;part&gt;</c>: prints the raw answers SOLIDWORKS 2024 gives
    /// for one document, so the questions research R5 left open - which traversal shape
    /// folders come back in, whether <c>GetChildren</c> and <c>GetParents</c> answer, whether
    /// <c>Description</c> reads, which type names the tables do not know, and whether a mate's
    /// feature reports its suppression - are settled by one run rather than by guesswork.
    ///
    /// Read-only: every call goes through the session's gate, and the probe writes no file.
    /// </summary>
    private static int RunProbe(string[] args)
    {
        CommandLine parsed;
        bool allowStart;

        try
        {
            if (args.Length < 2 || args[1].StartsWith("--", StringComparison.Ordinal))
            {
                throw new UsageError($"probe needs a subject: probe {RmsProbe} --doc <part>.");
            }

            if (!string.Equals(args[1], RmsProbe, StringComparison.Ordinal))
            {
                throw new UsageError($"Unknown probe '{args[1]}'; the only probe is {RmsProbe}.");
            }

            parsed = CommandLine.Parse(args, 2, KnownOptions(ProbeOptionNames));
            allowStart = parsed.Flag("allow-start");
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract probe: {error.Message}");
            return ExitError;
        }

        return ExecuteProbeRms(parsed.Value("doc"), allowStart);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteProbeRms(string? documentPath, bool allowStart)
    {
        using (var log = new ExtractLog(null))
        {
            try
            {
                ISldWorks swApp = Connect(allowStart, log);

                SwSession session = SwSession.Attach(swApp, documentPath, null);
                var refs = new PersistRefService(session.Gate);
                DocumentKind kind = SwSession.KindOf(session.Document, session.Gate);

                Out.WriteLine($"document: {session.DocumentPath}");
                Out.WriteLine($"kind: {PackageSerializer.EnumToJsonName(kind)}");
                Out.WriteLine("configuration: " + session.Gate.Call(
                    "Configuration.Name", () => session.Configuration.Name));
                Out.WriteLine("whats_wrong_count: " + Describe(() => session.Gate.Call(
                        "GetWhatsWrongCount",
                        () => session.Document.Extension.GetWhatsWrongCount())
                    .ToString(CultureInfo.InvariantCulture)));

                ProbeFeatures(session, refs);
                ProbeEquations(session);

                if (kind == DocumentKind.Assembly)
                {
                    ProbeAssembly(session, refs);
                }

                return ExitSuccess;
            }
            catch (Exception error)
            {
                log.WriteError("probe rms failed.", error);
                return ExitError;
            }
        }
    }

    /// <summary>
    /// The walk exactly as <see cref="FeatureDumper"/> sees it - same reader, same indexer -
    /// plus the raw per-feature answers the dump turns into nulls and gaps. Sub-feature counts
    /// beside depth are what show which traversal shape this release produces.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeFeatures(SwSession session, PersistRefService refs)
    {
        var reader = new SwFeatureReader(session.Gate, refs);
        IReadOnlyList<FeatureTreeNode> walk = reader.Walk(session.Document);
        IReadOnlyList<FeatureTreeRow> rows = FeatureTreeIndexer.Index(walk, new IdAllocator("feat"));
        string configuration = Describe(() => reader.ActiveConfiguration(session.Document));

        Out.WriteLine($"features: {rows.Count} (walked in '{configuration}')");
        Out.WriteLine("  index depth folder      subs  type_name / name");

        foreach (FeatureTreeRow row in rows)
        {
            object? handle = row.Node.Handle;
            Out.WriteLine(
                $"  {row.Index,5} {row.Depth,5} {row.FolderId ?? "-",-11} {row.Node.SubFeatures.Count,5}"
                + $"  {row.Node.TypeName} / {row.Node.Name}");

            if (handle == null)
            {
                Out.WriteLine("        (no live feature)");
                continue;
            }

            SwGate gate = session.Gate;
            Out.WriteLine(
                "        children="
                + Gated(gate, ProbeMember.Children, () => Count(reader.Children(handle)))
                + " parents="
                + Gated(gate, ProbeMember.Parents, () => Count(reader.Parents(handle)))
                + " suppressed="
                + Gated(
                    gate,
                    ProbeMember.Suppressed,
                    () => reader.Suppressed(handle, configuration).ToString())
                + " error_code="
                + Gated(
                    gate,
                    ProbeMember.ErrorCode,
                    () => reader.ErrorCode(handle).ToString(CultureInfo.InvariantCulture)));

            Out.WriteLine(
                "        description="
                + Gated(gate, ProbeMember.Description, () => Quote(reader.Description(handle)))
                + " sketch_status=" + Describe(() => SketchStatus(gate, reader, handle))
                + " definition=" + Describe(() => DescribeDefinition(gate, reader, handle)));
        }
    }

    /// <summary>
    /// The equation manager as the rules will read it: <c>GlobalVariable(i)</c> is the only
    /// honest source of "is this a global", and the probe prints it beside the text so a
    /// calibration run can see whether parsing the text would have agreed.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeEquations(SwSession session)
    {
        var manager = session.Gate.Call(
            "GetEquationMgr", () => session.Document.GetEquationMgr()) as IEquationMgr;

        if (manager == null)
        {
            Out.WriteLine("equations: (GetEquationMgr returned nothing)");
            return;
        }

        int count = session.Gate.Call("GetCount", () => manager.GetCount());
        Out.WriteLine($"equations: {count}");

        for (int i = 0; i < count; i++)
        {
            int index = i;
            Out.WriteLine(
                $"  [{index}] global="
                + Describe(() => session.Gate.Call(
                    "GlobalVariable", () => manager.GlobalVariable[index]).ToString())
                + " value=" + Describe(() => session.Gate.Call(
                        "EquationMgr.Value", () => manager.Value[index])
                    .ToString(CultureInfo.InvariantCulture))
                + " text=" + Describe(() => Quote(session.Gate.Call(
                    "EquationMgr.Equation", () => manager.Equation[index]))));
        }
    }

    /// <summary>
    /// The two assembly answers research R5 could not settle from the signatures: what
    /// <c>GetConstrainedStatus</c> reports per component, and whether a mate's feature reports
    /// its suppression. Both run through the shipped dumpers, so what the probe prints is what
    /// a dump would record, with the same component ids.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeAssembly(SwSession session, PersistRefService refs)
    {
        var gaps = new GapCollector();
        var options = new DumpOptions { Meshes = MeshFormat.None, Features = FeatureScope.None };
        ComponentTreeResult tree = new ComponentTreeDumper(session, refs).Traverse(gaps, options);
        DumpScope scope = PackageWriter.ScopeFor(gaps, options, tree);

        Out.WriteLine($"components: {scope.Components.Count}");
        foreach (ScopedComponent component in scope.Components)
        {
            ComponentNode node = component.Node;
            Out.WriteLine(
                $"  {component.Id} {node.Key}"
                + " constrained_status_raw="
                + (node.ConstrainedStatusRaw?.ToString(CultureInfo.InvariantCulture) ?? "null")
                + $" is_fixed={node.IsFixed}"
                + $" suppression={PackageSerializer.EnumToJsonName(node.Suppression)}");
        }

        IReadOnlyList<IrMate> mates = new MateDumper(session, refs).Dump(scope);
        Out.WriteLine($"mates: {mates.Count}");
        foreach (IrMate mate in mates)
        {
            var kinds = new List<string>();
            foreach (MateEntityRef entity in mate.Entities)
            {
                kinds.Add($"{entity.EntityKind}@{entity.ComponentId}");
            }

            Out.WriteLine($"  {mate.Id} {mate.Type} suppressed={mate.Suppressed} "
                + $"entities=[{string.Join(", ", kinds)}]");
        }

        Out.WriteLine($"gaps: {gaps.Count}");
        foreach (Gap gap in gaps.Gaps)
        {
            Out.WriteLine($"  {gap.EntityKind} {gap.EntityId ?? "-"}: {gap.Reason}");
        }
    }

    /// <summary>
    /// One probe reading. A member that throws is printed as the exception type rather than
    /// ending the run: which members fail on this release is half of what the probe is for.
    /// </summary>
    private static string Describe(Func<string> read)
    {
        try
        {
            return read();
        }
        catch (Exception error)
        {
            return $"!{error.GetType().Name}: {error.Message}";
        }
    }

    /// <summary>
    /// One probe reading, named to the gate first. The guard, the circuit breaker and the
    /// SC-004 observer all key on that name, so a read the probe does not name is a read
    /// the contract's "uses the read-only guard" does not cover.
    /// </summary>
    private static string Gated(SwGate gate, string interopMember, Func<string> read) =>
        Describe(() => gate.Call(interopMember, read));

    private static string Count(IReadOnlyList<object> items) =>
        items.Count.ToString(CultureInfo.InvariantCulture);

    private static string Quote(string? text) =>
        text == null ? "null" : text.Length == 0 ? "(blank)" : "\"" + text + "\"";

    private static string SketchStatus(SwGate gate, SwFeatureReader reader, object feature)
    {
        object? sketch = gate.Call(ProbeMember.Sketch, () => reader.Sketch(feature));
        return sketch == null
            ? "(not a sketch)"
            : gate.Call(ProbeMember.SketchStatus, () => reader.SketchConstrainedStatus(sketch))
                .ToString(CultureInfo.InvariantCulture);
    }

    /// <summary>
    /// Two of the three steps here are interop and are named to the gate; classifying the
    /// definition object is a cast, which is why <c>FeatureDumper</c> does not gate it either.
    /// </summary>
    private static string DescribeDefinition(SwGate gate, SwFeatureReader reader, object feature)
    {
        object? definition = gate.Call(ProbeMember.Definition, () => reader.Definition(feature));
        if (definition == null)
        {
            return "(none)";
        }

        string described = reader.DescribeDefinition(definition);
        switch (reader.ClassifyFillet(definition))
        {
            case FilletDefinitionKind.Simple:
                return described + " radius="
                    + gate.Call(
                            ProbeMember.Radius,
                            () => reader.SimpleFilletDefaultRadius(definition))
                        .ToString("G6", CultureInfo.InvariantCulture)
                    + " m";
            case FilletDefinitionKind.Variable:
                return described + " radius=(a variable fillet has none)";
            default:
                return described;
        }
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
        writer.WriteLine("                --features tree|none");
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
        writer.WriteLine("  probe rms     [--doc <path>]");
        writer.WriteLine("                Print the raw feature walk, sketch statuses, descriptions,");
        writer.WriteLine("                equations and fillet data for one document, and for an");
        writer.WriteLine("                assembly its component constrained status and mate");
        writer.WriteLine("                suppression. Writes nothing.");
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
