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
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Probes;
using SwReview.Extractor.Rms;
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
        { "doc", "config", "out", "meshes", "faces", "features", "equations", "profile", "reuse" };

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

    /// <summary>
    /// T031. <c>probe remodel</c> is a mutating command, unlike <c>probe rms</c> and
    /// <c>probe standards</c> above, so its options are its own list rather than
    /// <see cref="ProbeOptionNames"/>: it takes no <c>--doc</c> (it never addresses a document
    /// the engineer opened) and needs <c>--out</c>, the probe selection and the acknowledgement
    /// flag <c>--suppress-test</c>'s <c>--acknowledge-rebuild</c> precedent requires.
    /// </summary>
    internal static readonly string[] RemodelProbeOptionNames =
        { "probe", "out", "keep-part", "acknowledge-throwaway-part" };

    /// <summary>
    /// Feature 011 T081 (specs/011-drawing-context/contracts/probes.md section 1). <c>probe
    /// drawings</c> reads an open drawing or model like <c>probe standards</c>, so it takes
    /// <c>--doc</c>; it selects probes D1 to D14 with <c>--probe</c>; and unlike the other read-only
    /// probes it needs <c>--out</c>, because every run writes the report the owner brings back.
    /// </summary>
    internal static readonly string[] DrawingsProbeOptionNames = { "doc", "probe", "out" };

    /// <summary>
    /// T055. The one mutating command (contracts/cli.md). <c>--doc</c> is required rather
    /// than defaulting to the active document: this command suppresses features, and
    /// "whatever happens to be on screen" is not a model anyone chose to have modified.
    /// </summary>
    internal static readonly string[] SuppressTestOptionNames =
    {
        "doc", "plan", "acknowledge-rebuild", "out", "limit", "timeout-seconds",
    };

    /// <summary>
    /// The suppress-test's own log (contracts/cli.md). Separate from <c>extract.log</c>: it
    /// is the artifact SC-003 is audited against - the distinct interop members the one
    /// mutating command touched - and burying that in a dump log would lose it.
    /// </summary>
    internal const string SuppressTestLogFileName = "suppress-test.log";

    /// <summary>
    /// <c>probe remodel</c>'s own log (tasks.md T032), the same reason
    /// <see cref="SuppressTestLogFileName"/> is separate from <c>extract.log</c>: it is the
    /// record the capabilities ledger's interop members are audited against.
    /// </summary>
    internal const string RemodelProbeLogFileName = "remodel-probe.log";

    /// <summary>The feature 003 probe subject.</summary>
    private const string RmsProbe = "rms";

    /// <summary>
    /// The feature 006 probe subject: the ten workstation probes of <c>research.md</c> R4,
    /// printed in one read-only run (contracts/cli.md).
    /// </summary>
    private const string StandardsProbe = "standards";

    /// <summary>
    /// The feature 004 Phase 2 probe subject (tasks.md T031, T032): the stage-1 blocking and
    /// non-blocking probes of research.md R10, run against a throwaway part this command
    /// builds itself. Named <c>RemodelProbeSubject</c> rather than <c>RemodelProbe</c> so it
    /// cannot be confused with <see cref="RemodelProbe"/>, the pure logic class this subject
    /// dispatches to.
    /// </summary>
    private const string RemodelProbeSubject = "remodel";

    /// <summary>
    /// The feature 011 probe subject (tasks.md T081): probes D1 to D14 of
    /// specs/011-drawing-context/contracts/probes.md, read-only but for D14's one read-only open,
    /// each run writing its report in <c>--out</c>.
    /// </summary>
    private const string DrawingsProbeSubject = "drawings";

    /// <summary>
    /// The subjects <c>probe</c> accepts (contracts/cli.md). <see cref="RunProbe"/> validates
    /// against THIS list and names it in the usage error, so a subject the switch handles and
    /// the list does not - or the reverse - is a failing test rather than an "Unknown probe"
    /// discovered at the workstation.
    /// </summary>
    internal static readonly string[] ProbeSubjects =
        { RmsProbe, StandardsProbe, RemodelProbeSubject, DrawingsProbeSubject };

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
    /// The interop members <c>probe standards</c> names to the gate itself, by the name each
    /// is gated under. Named once so the call sites and
    /// <see cref="StandardsProbeInteropMembers"/> cannot drift apart - the same reason
    /// <see cref="ProbeMember"/> exists.
    ///
    /// Only the members the probe names: the shipped readers
    /// (<c>SwDrawingReader</c>, <c>SwCutListReader</c>, <c>SwFeatureReader</c>,
    /// <c>PersistRefService</c>) gate the rest themselves, and a member gated twice would be
    /// a gate log that counts calls nobody made. The names are bare because
    /// <c>SwGate.Call</c> names them bare; the two dotted ones disambiguate a bare name that
    /// belongs to two different interfaces, the way <c>ConfigurationManager.ActiveConfiguration</c>
    /// and <c>ITableAnnotation.Type</c> already do elsewhere.
    /// </summary>
    private static class StandardsProbeMember
    {
        // The run's own header, and the check that stops SwSession.Attach opening anything.
        public const string OpenDocumentByName = "GetOpenDocumentByName";
        public const string PathName = "GetPathName";
        public const string ConfigurationName = "Configuration.Name";

        // PROBE-1, the exploded read.
        public const string IsExploded = "IsExploded";
        public const string ExtensionIsExploded = "IModelDocExtension.IsExploded";
        public const string ConfigurationNames = "GetConfigurationNames";
        public const string ConfigurationByName = "GetConfigurationByName";
        public const string ExplodeSteps = "GetNumberOfExplodeSteps";
        public const string ModelDoc2 = "GetModelDoc2";

        // PROBE-2, the transparency-override polarity.
        public const string HasMaterialPropertyValues = "HasMaterialPropertyValues";
        public const string MaterialPropertyValues = "GetMaterialPropertyValues2";

        // PROBE-3, component visibility.
        public const string Visible = "Visible";
        public const string Visibility = "GetVisibility";

        // PROBE-4, the revision-table read.
        public const string RevisionTable = "RevisionTable";
        public const string TableType = "ITableAnnotation.Type";
        public const string CurrentRevision = "CurrentRevision";
        public const string TotalRowCount = "TotalRowCount";
        public const string CellText = "Text";
        public const string CellDisplayedText = "DisplayedText";

        // PROBE-5's note walk and PROBE-7's sheet enumeration.
        public const string Sheet = "Sheet";
        public const string Views = "GetViews";

        /// <summary>
        /// <c>ISheet.GetName()</c> and <c>IAnnotation.GetName()</c> are one bare name to the
        /// gate, so they are one constant here: two constants with one value would read as
        /// two members in a log that cannot tell them apart.
        /// </summary>
        public const string Name = "GetName";

        public const string ViewTypeMember = "Type";
        public const string Notes = "GetNotes";
        public const string NoteText = "GetText";
        public const string FirstView = "GetFirstView";
        public const string NextView = "GetNextView";

        // PROBE-6, the drawing-view and annotation walk.
        public const string ViewName = "GetName2";
        public const string ReferencedModelName = "GetReferencedModelName";
        public const string ReferencedDocument = "ReferencedDocument";
        public const string Annotations = "GetAnnotations";
        public const string AnnotationCount = "GetAnnotationCount";
        public const string FirstAnnotation = "GetFirstAnnotation3";
        public const string NextAnnotation = "GetNext3";
        public const string AnnotationType = "GetType";
        public const string Dangling = "IsDangling";
        public const string DisplayDimensions = "GetDisplayDimensions";
        public const string DimensionType = "Type2";
        public const string Override = "GetOverride";
        public const string OverrideValue = "GetOverrideValue";

        // PROBE-8, the cut-list walk.
        public const string FeatureName = "Feature.Name";
        public const string TypeName = "GetTypeName2";
        public const string SpecificFeature = "GetSpecificFeature2";
        public const string BodyCount = "GetBodyCount";
        public const string ExcludeFromCutList = "ExcludeFromCutList";

        // PROBE-9, the sketch text-segment read.
        public const string SketchTextSegments = "GetSketchTextSegments";

        // PROBE-10, the persistent references.
        public const string PersistReferenceCount = "GetPersistReferenceCount3";
    }

    /// <summary>
    /// Every interop member <c>probe standards</c> names to the gate, in the order the run
    /// first names it (contracts/cli.md row 20, <c>research.md</c> R4).
    ///
    /// The list exists so the option tests can assert that every one of them passes
    /// <see cref="ReadOnlyGuard"/>: the shipped readers leave these members ungated on purpose
    /// - their dumpers name them - so on this path the probe is the caller. Ungated they would
    /// reach no guard, no circuit breaker and no observer, and the gate log this command
    /// prints as its proof would be missing exactly the reads it printed.
    /// </summary>
    internal static readonly string[] StandardsProbeInteropMembers =
    {
        StandardsProbeMember.OpenDocumentByName,
        StandardsProbeMember.PathName,
        StandardsProbeMember.ConfigurationName,

        StandardsProbeMember.IsExploded,
        StandardsProbeMember.ExtensionIsExploded,
        StandardsProbeMember.ConfigurationNames,
        StandardsProbeMember.ConfigurationByName,
        StandardsProbeMember.ExplodeSteps,
        StandardsProbeMember.ModelDoc2,

        StandardsProbeMember.HasMaterialPropertyValues,
        StandardsProbeMember.MaterialPropertyValues,

        StandardsProbeMember.Visible,
        StandardsProbeMember.Visibility,

        StandardsProbeMember.RevisionTable,
        StandardsProbeMember.TableType,
        StandardsProbeMember.CurrentRevision,
        StandardsProbeMember.TotalRowCount,
        StandardsProbeMember.CellText,
        StandardsProbeMember.CellDisplayedText,

        StandardsProbeMember.Sheet,
        StandardsProbeMember.Views,
        StandardsProbeMember.Name,
        StandardsProbeMember.ViewTypeMember,
        StandardsProbeMember.Notes,
        StandardsProbeMember.NoteText,
        StandardsProbeMember.FirstView,
        StandardsProbeMember.NextView,

        StandardsProbeMember.ViewName,
        StandardsProbeMember.ReferencedModelName,
        StandardsProbeMember.ReferencedDocument,
        StandardsProbeMember.Annotations,
        StandardsProbeMember.AnnotationCount,
        StandardsProbeMember.FirstAnnotation,
        StandardsProbeMember.NextAnnotation,
        StandardsProbeMember.AnnotationType,
        StandardsProbeMember.Dangling,
        StandardsProbeMember.DisplayDimensions,
        StandardsProbeMember.DimensionType,
        StandardsProbeMember.Override,
        StandardsProbeMember.OverrideValue,

        StandardsProbeMember.FeatureName,
        StandardsProbeMember.TypeName,
        StandardsProbeMember.SpecificFeature,
        StandardsProbeMember.BodyCount,
        StandardsProbeMember.ExcludeFromCutList,

        StandardsProbeMember.SketchTextSegments,

        StandardsProbeMember.PersistReferenceCount,
    };

    /// <summary>
    /// The members whose ABSENCE from the gate log is contracts/cli.md's "activates no
    /// sheet". <c>ActivateSheet</c> and <c>ActivateView</c> are on the read-only denylist and
    /// would be refused anyway; <c>SheetNext</c> and <c>SheetPrevious</c> are not, and they
    /// activate a sheet just as surely, which is why the claim is checked against a list of
    /// its own rather than against the denylist.
    /// </summary>
    internal static readonly string[] StandardsProbeSheetActivationMembers =
        { "ActivateSheet", "ActivateView", "SheetNext", "SheetPrevious" };

    /// <summary>
    /// The members whose absence is "opens no document". <c>OpenDoc6</c> is the extractor's
    /// one file-opening call (<c>SwSession.OpenReadOnly</c>); the other three are the
    /// neighbouring ways in, listed so the claim does not rest on one spelling.
    /// </summary>
    internal static readonly string[] StandardsProbeDocumentOpeningMembers =
        { "OpenDoc6", "OpenDoc7", "LoadFile4", "ActivateDoc3" };

    /// <summary>
    /// The members whose absence is "changes no display state" - what the engineer would see
    /// differently afterwards. Several are on the read-only denylist as well; the list is
    /// written out because the claim the log makes is about these members, not about whatever
    /// the denylist happens to hold.
    /// </summary>
    internal static readonly string[] StandardsProbeDisplayStateMembers =
    {
        "ShowConfiguration2", "ShowNamedView2", "ViewZoomtofit2", "GraphicsRedraw2",
        "ShowExploded", "ShowExploded2", "SetVisibility", "SetVisibilityInAsmDisplayStates",
        "set_Visible",
    };

    /// <summary>
    /// How deep <c>probe standards</c> walks sub-features. The cut list is one level of items
    /// under one folder, so four is three more than anything expected; the probe prints that
    /// it stopped rather than recursing without a bound on a tree that answers in a cycle.
    /// </summary>
    private const int StandardsProbeMaxDepth = 4;

    /// <summary>
    /// How many items either linked-list walk - <c>GetFirstView</c>/<c>GetNextView</c> and
    /// <c>GetFirstAnnotation3</c>/<c>GetNext3</c> - may list. Same bound, same reason as
    /// <see cref="StandardsProbeMaxDepth"/>: a list that never ends must stop the probe, not
    /// the workstation.
    /// </summary>
    private const int StandardsProbeMaxWalk = 10000;

    /// <summary>
    /// The gate <c>probe standards</c> runs on: the READ-ONLY guard, watched by a recorder so
    /// the distinct member names reach the gate log the command prints at the end
    /// (contracts/cli.md row 20). Built here rather than left to <c>SwSession</c>'s default,
    /// so the guard this command carries is a decision the option tests can see - and it is
    /// never <see cref="SuppressTestGuard"/>, the only other <c>ICallGuard</c> in the product.
    /// </summary>
    internal static SwGate StandardsProbeGate(RecordingGateObserver observer) =>
        new SwGate(new CircuitBreaker(), ReadOnlyCallGuard.Instance) { Observer = observer };

    /// <summary>
    /// Why <c>probe standards</c> will not run on a document that is not already open:
    /// <c>SwSession.Attach</c> would open it read-only - the extractor's one file-opening
    /// call - and this command's own gate log is the proof that it opened nothing.
    /// </summary>
    internal static string StandardsProbeDocumentNotOpenMessage(string documentPath) =>
        $"'{documentPath}' is not open in SOLIDWORKS. Open it first: probe standards opens no "
        + "document, and its gate log is the proof - a run that had opened this one would be "
        + "proving the opposite of what it was asked to prove.";

    /// <summary>
    /// Why <c>probe drawings</c> will not run on a document that is not already open: the same
    /// reason as <see cref="StandardsProbeDocumentNotOpenMessage"/>. The one document it may open is
    /// D14's same-name drawing, read-only and hidden through the confirmed open's own seam - never
    /// the document it was pointed at. Printed on the console only; the report names no path.
    /// </summary>
    internal static string DrawingsProbeDocumentNotOpenMessage(string documentPath) =>
        $"'{documentPath}' is not open in SOLIDWORKS. Open it first: probe drawings opens no document "
        + "it is pointed at - D14's read-only open of the same-name drawing is the only open it makes.";

    /// <summary>The report's line for the same refusal, with no path in it.</summary>
    private const string DrawingsProbeNotOpenReportLine =
        "refused: the named document is not open in SOLIDWORKS, so nothing was read and nothing was opened";

    /// <summary>
    /// The gate log <c>probe standards</c> prints at the end of every run, successful or not
    /// (contracts/cli.md row 20, quickstart scenario 9).
    ///
    /// Four claims, each on its own line and each naming what it watched for, because a bare
    /// "none" is only worth reading beside the list it is none of. The mutating line asks
    /// <see cref="ReadOnlyGuard"/> itself rather than carrying a copy of the denylist, so a
    /// member added to the guard is covered here the same day.
    /// </summary>
    internal static IReadOnlyList<string> StandardsProbeGateLogLines(
        IReadOnlyList<string> gatedMembers, IReadOnlyList<MutatingCallError> refusals)
    {
        IReadOnlyList<string> members = gatedMembers ?? new string[0];
        var mutating = new List<string>();
        foreach (string member in members)
        {
            if (IsMutating(member))
            {
                mutating.Add(member);
            }
        }

        var reasons = new List<string>();
        if (refusals != null)
        {
            foreach (MutatingCallError refusal in refusals)
            {
                reasons.Add(refusal.Message);
            }
        }

        return new[]
        {
            $"gate log: the read-only guard, {members.Count} distinct interop members",
            "  members: " + Listed(members),
            "  mutating members: " + Listed(mutating),
            "  refusals: " + Listed(reasons),
            Claim("sheet activation", members, StandardsProbeSheetActivationMembers),
            Claim("document opening", members, StandardsProbeDocumentOpeningMembers),
            Claim("display state", members, StandardsProbeDisplayStateMembers),
        };
    }

    /// <summary>One gate-log claim: what of <paramref name="watched"/> the run actually touched.</summary>
    private static string Claim(string name, IReadOnlyList<string> members, string[] watched)
    {
        var touched = new List<string>();
        foreach (string member in watched)
        {
            foreach (string seen in members)
            {
                if (string.Equals(seen, member, StringComparison.OrdinalIgnoreCase))
                {
                    touched.Add(member);
                    break;
                }
            }
        }

        return $"  {name}: {Listed(touched)}  (watched: {string.Join(", ", watched)})";
    }

    /// <summary>
    /// Would the read-only guard refuse this member? Asked of the guard rather than
    /// re-implemented, so the prefix families and the denylist cannot get two answers.
    /// A handful of names at the end of a run, so the throw costs nothing worth saving.
    /// </summary>
    private static bool IsMutating(string member)
    {
        try
        {
            ReadOnlyGuard.Assert(member);
            return false;
        }
        catch (MutatingCallError)
        {
            return true;
        }
    }

    /// <summary>A gate-log list, or the word that says the list was empty.</summary>
    private static string Listed(IReadOnlyList<string> items)
    {
        if (items.Count == 0)
        {
            return "none";
        }

        var parts = new string[items.Count];
        for (int i = 0; i < items.Count; i++)
        {
            parts[i] = items[i];
        }

        return string.Join(", ", parts);
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

            case "suppress-test":
                return RunSuppressTest(args);

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

        bool reuse;

        try
        {
            parsed = CommandLine.Parse(args, 1, KnownOptions(DumpOptionNames));
            allowStart = parsed.Flag("allow-start");

            // Feature 005 lever 9, off unless asked for: a dump that quietly copied an earlier
            // package would be a dump that answered about a design nobody checked was the one
            // on screen.
            reuse = parsed.Flag("reuse");
            options = new DumpOptions
            {
                OutputDirectory = parsed.Required("out"),
                Configuration = parsed.Value("config"),
                Meshes = parsed.MeshFormat(),
                Faces = parsed.FaceScope(),
                Features = parsed.FeatureScope(),
                Equations = parsed.EquationScope(),
                Profile = parsed.DumpProfile(),
            };
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract dump: {error.Message}");
            return ExitError;
        }

        return ExecuteDump(options, parsed.Value("doc"), allowStart, reuse);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteDump(DumpOptions options, string? documentPath, bool allowStart, bool reuse)
    {
        var observer = new RecordingGateObserver();
        using (var log = new ExtractLog(options.OutputDirectory))
        {
            try
            {
                log.Write($"dump --out \"{options.OutputDirectory}\" "
                    + $"--meshes {options.Meshes.ToString().ToLowerInvariant()} "
                    + $"--faces {options.Faces.ToString().ToLowerInvariant()} "
                    + $"--features {options.Features.ToString().ToLowerInvariant()} "
                    + $"--equations {options.Equations.ToString().ToLowerInvariant()} "
                    + $"--profile {CommandLine.CliName(options.Profile)}");

                ISldWorks swApp = Connect(allowStart, log);

                // The extraction's attach (feature 011, contracts/attach.md section 3): a drawing
                // is read with no configuration, and one that is not open is refused, not opened.
                // The gate is watched, so the log's last line names every member the dump asked
                // about (feature 010 T109).
                ISwSession session = SwSession.AttachForDump(
                    swApp, documentPath, options.Configuration, DumpGate(observer));
                log.Write($"Document: {session.Document.GetPathName()}");
                log.Write("Configuration: "
                    + (session.ConfigurationName() ?? "none (a drawing has no configuration)"));

                PackageWriter writer = SwDump.CreateWriter(swApp, session);
                string? runRoot = RunRootOf(options.OutputDirectory);
                DumpResult result = Extract(writer, options, session, runRoot, reuse, log);

                RecordInIndex(result, options, runRoot, log);

                log.Write($"Wrote {result.PackageFilePath}");
                log.Write($"{result.Package.Components.Count} components, "
                    + $"{result.Package.Features.Count} features, "
                    + $"{result.Package.Equations.Count} equations, "
                    + $"{result.Package.Holes.Count} holes, "
                    + $"{result.Package.Fasteners.Count} fasteners, "
                    + $"{result.Package.Faces.Count} faces, "
                    + $"{result.Package.Bodies.Count} bodies, "
                    + $"{result.Gaps.Count} gaps");
                log.Write(DumpGateLogLine(observer.Members));

                Out.WriteLine(result.PackageFilePath);
                return ExitSuccess;
            }
            catch (Exception error)
            {
                log.WriteError("dump failed.", error);
                log.Write(DumpGateLogLine(observer.Members));
                return ExitError;
            }
        }
    }

    /// <summary>
    /// The gate <c>dump</c> runs on (feature 010 T109, the seat-readiness review of 2026-09-23):
    /// the READ-ONLY guard, as <c>SwSession</c>'s default gate has, watched by a recorder so
    /// <c>extract.log</c> ends with every interop member the dump asked about. That set is how a
    /// seat sees which mass-override path answered: <c>PropertyDumper.ReadMassOverridden</c> asks
    /// <c>GetOverrideOptions</c> only when <c>CreateMassProperty</c>'s path gave no answer.
    /// </summary>
    internal static SwGate DumpGate(RecordingGateObserver observer) =>
        new SwGate(new CircuitBreaker(), ReadOnlyCallGuard.Instance) { Observer = observer };

    /// <summary>
    /// The dump's gate-log line: <c>gated=</c> and every member once, in first-seen order - the
    /// shape of the tool service's own <c>gated=</c> field.
    /// </summary>
    internal static string DumpGateLogLine(IReadOnlyList<string> members) =>
        "gated=" + string.Join(",", members);

    /// <summary>
    /// Dumps, or - with <c>--reuse</c> - copies an earlier run's package into this run's
    /// output directory instead (feature 005 lever 9, T091).
    ///
    /// The decision is stated either way, in <c>extract.log</c> and on the package itself: a
    /// run that reused an extraction and did not say so is a run whose evidence nobody can
    /// date. A refusal falls through to the dump rather than failing the command, because the
    /// worst outcome of a miss is the extraction the caller asked to skip.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static DumpResult Extract(
        PackageWriter writer,
        DumpOptions options,
        ISwSession session,
        string? runRoot,
        bool reuse,
        ExtractLog log)
    {
        if (!reuse)
        {
            return writer.Write(options);
        }

        // The key is recomputed from the live document's references now, never trusted from
        // the file: a stored key that matches a document that has moved is the one thing this
        // mechanism must not do.
        ReuseOutcome outcome = PackageReuse.Reuse(
            writer.BuildReuseProbe(options), options, runRoot, SaveFlag(session, log), DateTimeOffset.Now);

        log.Write(outcome.Message);
        foreach (ReuseRefusal refusal in outcome.Refusals)
        {
            log.Write($"  [{refusal.Code}] {refusal.Reason}");
        }

        return outcome.Result ?? writer.Write(options);
    }

    /// <summary>
    /// Whether the active document has edits that are not on disk, or null when the answer
    /// could not be read. Null refuses reuse, exactly as true does: a modification time cannot
    /// see an in-memory edit, so an unreadable save flag is not a reason to assume there is
    /// none.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static bool? SaveFlag(ISwSession session, ExtractLog log)
    {
        try
        {
            return session.Gate.Call("GetSaveFlag", session.Document.GetSaveFlag);
        }
        catch (Exception error)
        {
            log.Write($"The document's save state could not be read: {error.Message}");
            return null;
        }
    }

    /// <summary>
    /// The run root: the directory the run folders sit in, which is the parent of this run's
    /// <c>--out</c>. The index lives there because it is about the folders, not about any one
    /// of them.
    /// </summary>
    private static string? RunRootOf(string outputDirectory)
    {
        try
        {
            return Path.GetDirectoryName(Path.GetFullPath(outputDirectory));
        }
        catch (Exception error) when (error is ArgumentException || error is NotSupportedException
            || error is PathTooLongException || error is System.Security.SecurityException)
        {
            return null;
        }
    }

    /// <summary>
    /// Appends this run folder to the run root's index, so a later <c>--reuse</c> can find it
    /// without opening a package. A line that cannot be written is logged and nothing more:
    /// the package is on disk either way, and the only cost is a future miss.
    /// </summary>
    private static void RecordInIndex(
        DumpResult result, DumpOptions options, string? runRoot, ExtractLog log)
    {
        if (result.Package.ReuseKey == null || runRoot == null)
        {
            return;
        }

        var row = new PackageIndexRow
        {
            ReuseKey = result.Package.ReuseKey,
            Folder = Path.GetFileName(Path.GetFullPath(options.OutputDirectory).TrimEnd(
                Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)),
            WrittenAt = DateTimeOffset.Now,
            Profile = PackageSerializer.EnumToJsonName(options.Profile),
            PackageBytes = PackageIndex.PackageBytes(options.OutputDirectory),
        };

        if (!PackageIndex.Append(runRoot, row))
        {
            log.Write($"The run index under {runRoot} could not be updated; the package is unaffected.");
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

            // Lever 10a: `tessellate` writes its meshes under the same directory captures go
            // to, which is this host's --out and never anything a request names.
            TessellateSource = scope.TessellateSource(),
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
    internal static int RunProbe(string[] args)
    {
        CommandLine parsed;
        bool allowStart;
        string subject;

        try
        {
            if (args.Length < 2 || args[1].StartsWith("--", StringComparison.Ordinal))
            {
                throw new UsageError(
                    "probe needs a subject: probe "
                    + string.Join("|", ProbeSubjects) + " --doc <document> (rms, standards), "
                    + "probe drawings --out <dir> [--doc <document>] [--probe D1,...], "
                    + "or probe remodel --out <dir>.");
            }

            subject = args[1];
            if (!IsProbeSubject(subject))
            {
                throw new UsageError(
                    $"Unknown probe '{subject}'; the probes are {string.Join(", ", ProbeSubjects)}.");
            }

            // probe remodel is the one mutating probe (tasks.md T031) and takes none of
            // ProbeOptionNames' --doc: it never addresses a document the engineer opened. probe
            // drawings (feature 011 T081) adds --probe and the report's --out.
            string[] optionNames = string.Equals(subject, RemodelProbeSubject, StringComparison.Ordinal)
                ? RemodelProbeOptionNames
                : string.Equals(subject, DrawingsProbeSubject, StringComparison.Ordinal)
                    ? DrawingsProbeOptionNames
                    : ProbeOptionNames;

            parsed = CommandLine.Parse(args, 2, KnownOptions(optionNames));
            allowStart = parsed.Flag("allow-start");
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract probe: {error.Message}");
            return ExitError;
        }

        if (string.Equals(subject, RemodelProbeSubject, StringComparison.Ordinal))
        {
            return RunRemodelProbe(parsed, allowStart);
        }

        if (string.Equals(subject, DrawingsProbeSubject, StringComparison.Ordinal))
        {
            return RunDrawingsProbe(parsed, allowStart);
        }

        return string.Equals(subject, StandardsProbe, StringComparison.Ordinal)
            ? ExecuteProbeStandards(parsed.Value("doc"), allowStart)
            : ExecuteProbeRms(parsed.Value("doc"), allowStart);
    }

    /// <summary>
    /// T032. <c>probe remodel</c>'s own refusal (contracts/cli.md's "refuses, before touching
    /// anything" pattern, the <c>suppress-test</c> precedent): a missing
    /// <c>--acknowledge-throwaway-part</c> is caught here, before <see cref="Connect"/> ever
    /// runs, so a refused run never asks SOLIDWORKS for anything.
    /// </summary>
    private static int RunRemodelProbe(CommandLine parsed, bool allowStart)
    {
        RemodelProbeSettings settings;
        try
        {
            settings = RemodelProbeSettingsFrom(parsed);
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract probe remodel: {error.Message}");
            return ExitError;
        }

        if (!settings.Acknowledged)
        {
            Error.WriteLine($"swreview-extract probe remodel: {RemodelProbe.AcknowledgementRequiredMessage}");
            return ExitError;
        }

        return ExecuteProbeRemodel(settings, allowStart);
    }

    /// <summary>
    /// The command line as the run settings, defaults included (the
    /// <see cref="SuppressTestSettingsFrom"/> precedent): the option tests assert against THIS
    /// method rather than a copy of the defaults.
    /// </summary>
    internal static RemodelProbeSettings RemodelProbeSettingsFrom(CommandLine parsed)
    {
        if (parsed == null)
        {
            throw new ArgumentNullException(nameof(parsed));
        }

        IReadOnlyList<string> rawProbeValues = parsed.Values("probe");
        IReadOnlyList<string> probeIds = rawProbeValues.Count == 0
            ? RemodelProbeCatalog.AllIds
            : SplitProbeIds(rawProbeValues, RemodelProbeCatalog.IsKnown, RemodelProbeCatalog.AllIds);

        var settings = new RemodelProbeSettings
        {
            OutputDirectory = parsed.Required("out"),
            KeepPart = parsed.Flag("keep-part"),
            Acknowledged = parsed.Flag("acknowledge-throwaway-part"),
            ProbeIds = probeIds,
        };

        return settings;
    }

    /// <summary>
    /// <c>--probe id,id,...</c>, one or more tokens each holding a comma-separated list, the
    /// same shape <c>--pairs</c> already accepts. Every id is upper-cased and checked against
    /// the probe family's own catalog (<paramref name="isKnown"/>, <paramref name="known"/>) here,
    /// at parse time, so a typo is a usage error rather than a silently unresolved row
    /// (contracts/cli.md). One parser for <c>probe remodel</c> and <c>probe drawings</c>.
    /// </summary>
    private static IReadOnlyList<string> SplitProbeIds(
        IReadOnlyList<string> rawValues, Func<string, bool> isKnown, IReadOnlyList<string> known)
    {
        var ids = new List<string>();
        foreach (string raw in rawValues)
        {
            foreach (string piece in raw.Split(','))
            {
                string id = piece.Trim().ToUpperInvariant();
                if (id.Length == 0)
                {
                    continue;
                }

                if (!isKnown(id))
                {
                    throw new UsageError(
                        $"--probe names an unknown probe '{id}'; the probes are "
                        + string.Join(", ", known) + ".");
                }

                ids.Add(id);
            }
        }

        if (ids.Count == 0)
        {
            throw new UsageError("--probe needs at least one probe id.");
        }

        return ids;
    }

    /// <summary>
    /// The guard <c>probe remodel</c> builds its gate with: <see cref="RemodelProbeGuard"/>,
    /// never the stage-1 <see cref="RemodelGuard"/> allowlist, which refuses the whole
    /// feature-creation family this probe deliberately builds (contracts/guard-allowlist.md).
    /// </summary>
    internal static SwGate RemodelProbeGate(RecordingGateObserver observer) =>
        new SwGate(new CircuitBreaker(), new RemodelProbeGuard()) { Observer = observer };

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteProbeRemodel(RemodelProbeSettings settings, bool allowStart)
    {
        var observer = new RecordingGateObserver();

        using (var log = new ExtractLog(settings.OutputDirectory, RemodelProbeLogFileName))
        {
            try
            {
                log.Write($"probe remodel --probe {string.Join(",", settings.ProbeIds)} "
                    + $"--out \"{settings.OutputDirectory}\""
                    + (settings.KeepPart ? " --keep-part" : string.Empty));

                ISldWorks swApp = Connect(allowStart, log);
                SwGate gate = RemodelProbeGate(observer);
                var host = new SwRemodelProbeHost(swApp, gate);

                if (host.AnyDocumentOpen())
                {
                    throw new RemodelProbeRefusedError(RemodelProbe.DocumentAlreadyOpenMessage);
                }

                string swVersion = host.SwVersion();
                string partPath = Path.Combine(
                    settings.OutputDirectory, "probe-part", "remodel-probe.SLDPRT");
                RemodelProbe.AssertPartSavePath(partPath, settings.OutputDirectory);

                IReadOnlyList<RemodelProbeRecord>? records = null;
                RemodelSystemToggles.Within(host, gate, () =>
                {
                    // If BuildPart itself throws partway through the recipe, SOLIDWORKS may be
                    // left holding an unsaved, unreferenced document: there is nothing to close
                    // or delete from here, because no RemodelProbePart was ever produced. The
                    // next run's AnyDocumentOpen() check will refuse rather than proceed against
                    // it, which is the safe failure - not a silent one - for a build failure
                    // this early is itself evidence for whichever probe was building.
                    RemodelProbePart part = host.BuildPart(RemodelProbePartRecipe.Default(), partPath);
                    try
                    {
                        var context = new RemodelProbeContext(part, gate, swVersion, host, settings.OutputDirectory);
                        records = RemodelProbeRunner.RunAll(settings.ProbeIds, context);
                    }
                    finally
                    {
                        host.ClosePart(part);
                        if (!settings.KeepPart)
                        {
                            TryDeleteProbePart(part.Path);
                        }
                    }
                });

                string ledgerPath = RemodelProbeLedger.Write(settings.OutputDirectory, swVersion, records!);

                foreach (string line in RemodelProbe.LogLines(records!, observer.Members, ledgerPath))
                {
                    log.Write(line);
                }

                Out.WriteLine(ledgerPath);
                return ExitSuccess;
            }
            catch (RemodelProbeRefusedError refusal)
            {
                log.WriteError("probe remodel refused, and nothing was built.", refusal);
                return ExitError;
            }
            catch (Exception error)
            {
                log.WriteError("probe remodel failed.", error);
                return ExitError;
            }
        }
    }

    /// <summary>
    /// Deletes the throwaway part's file (and its now-empty <c>probe-part/</c> directory)
    /// unless <c>--keep-part</c> was given. Never throws: a part that could not be deleted is
    /// reported in the log, not turned into a run the engineer thinks failed to measure
    /// anything.
    /// </summary>
    private static void TryDeleteProbePart(string partPath)
    {
        try
        {
            if (File.Exists(partPath))
            {
                File.Delete(partPath);
            }

            string? directory = Path.GetDirectoryName(partPath);
            if (!string.IsNullOrEmpty(directory) && Directory.Exists(directory)
                && Directory.GetFileSystemEntries(directory).Length == 0)
            {
                Directory.Delete(directory);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    /// <summary>
    /// T081. <c>probe drawings</c>'s own parse, done before <see cref="Connect"/> runs so a bad
    /// command line never asks SOLIDWORKS for anything (the <c>probe remodel</c> precedent).
    /// </summary>
    private static int RunDrawingsProbe(CommandLine parsed, bool allowStart)
    {
        DrawingProbeSettings settings;
        try
        {
            settings = DrawingsProbeSettingsFrom(parsed);
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract probe drawings: {error.Message}");
            return ExitError;
        }

        return ExecuteProbeDrawings(settings, allowStart);
    }

    /// <summary>
    /// The command line as <c>probe drawings</c>' settings (specs/011-drawing-context/contracts/
    /// probes.md section 1): <c>--out</c> required, <c>--doc</c> optional (the active document), and
    /// <c>--probe</c> validated against <see cref="DrawingProbeCatalog"/> and put in catalog order,
    /// or null - the default for the open document's kind, which is known only once attached.
    /// </summary>
    internal static DrawingProbeSettings DrawingsProbeSettingsFrom(CommandLine parsed)
    {
        if (parsed == null)
        {
            throw new ArgumentNullException(nameof(parsed));
        }

        string outputDirectory = parsed.Required("out");
        IReadOnlyList<string>? probeIds = parsed.Has("probe")
            ? DrawingProbeCatalog.InCatalogOrder(
                SplitProbeIds(parsed.Values("probe"), DrawingProbeCatalog.IsKnown, DrawingProbeCatalog.AllIds))
            : null;

        return new DrawingProbeSettings
        {
            OutputDirectory = outputDirectory,
            DocumentPath = parsed.Value("doc"),
            ProbeIds = probeIds,
        };
    }

    /// <summary>
    /// The report's line for the confirmed open's own gate (D14): the members its guard saw, which
    /// the read-only gate's log above it cannot show - <c>ISldWorks.OpenDoc6</c> is gated there
    /// under its qualified key, never on the read-only gate.
    /// </summary>
    internal static string DrawingsProbeSeamGateLogLine(IReadOnlyList<string> seamMembers) =>
        "gate log: the confirmed open's guard (DrawingOpenGuard, D14 only): "
        + (seamMembers == null || seamMembers.Count == 0 ? "none" : string.Join(", ", seamMembers));

    /// <summary>
    /// T081. <c>probe drawings</c> (specs/011-drawing-context/contracts/probes.md): attaches to the
    /// open document on the read-only guard watched by a recorder, refuses a named document that is
    /// not open, runs the selected probes through <see cref="DrawingProbeRunner"/>, and prints the
    /// report - the header, every section, the read-only gate log and the confirmed open's - whether
    /// or not a probe failed. The same lines are written to <c>drawings-probe-&lt;UTC time&gt;.txt</c>
    /// in <c>--out</c>, the one file the run writes; the report names no path, and a stop's full
    /// message goes to stderr only.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteProbeDrawings(DrawingProbeSettings settings, bool allowStart)
    {
        var observer = new RecordingGateObserver();
        SwGate gate = StandardsProbeGate(observer);
        var seamObserver = new RecordingGateObserver();
        DateTimeOffset startedAt = DateTimeOffset.UtcNow;
        System.Diagnostics.Stopwatch clock = System.Diagnostics.Stopwatch.StartNew();
        string? swVersion = null;
        DocumentKind? kind = null;
        IReadOnlyList<string> probeIds = settings.ProbeIds ?? Array.Empty<string>();
        var sections = new List<string>();
        int exitCode;

        using (var log = new ExtractLog(null))
        {
            try
            {
                ISldWorks swApp = Connect(allowStart, log);
                string? documentPath = settings.DocumentPath;

                // SwSession.AttachForDump would OPEN a named part or assembly that is not open. This
                // run opens nothing it is pointed at, so such a document is refused before anything
                // else is asked of it - as probe standards refuses it.
                if (!string.IsNullOrWhiteSpace(documentPath) && !IsOpenDocument(gate, swApp, documentPath!))
                {
                    log.Write(DrawingsProbeDocumentNotOpenMessage(documentPath!));
                    sections.Add(DrawingsProbeNotOpenReportLine);
                    exitCode = ExitError;
                }
                else
                {
                    ISwSession session = SwSession.AttachForDump(swApp, documentPath, null, gate);
                    swVersion = session.SwVersion;
                    DocumentKind documentKind = SwSession.KindOf(session.Document, gate);
                    kind = documentKind;
                    probeIds = settings.ProbeIds ?? DrawingProbeCatalog.DefaultFor(documentKind);

                    var refs = new PersistRefService(gate);
                    string? path = gate.Call(StandardsProbeMember.PathName, () => session.Document.GetPathName());
                    var context = new DrawingProbeContext(
                        documentKind,
                        path,
                        session.Document,
                        options => SwDump.CreateWriter(swApp, session).Build(options),
                        (modelPath, options) => BuildOpenModel(swApp, gate, modelPath, options),
                        new SwOpenDrawingReader(swApp, gate),
                        new SwDrawingProbeReads(swApp, session, refs),
                        new ProbeFiles(),
                        new DrawingOpenProbeSeam(
                            new SwDrawingOpenProbeHost(swApp),
                            new DrawingDumper(gate, new SwDrawingReader(session, refs)),
                            gate,
                            seamObserver),
                        () => clock.ElapsedMilliseconds);

                    sections.AddRange(DrawingProbeRunner.Run(probeIds, context));
                    exitCode = ExitSuccess;
                }
            }
            catch (Exception error)
            {
                // The report still prints and is still written: "what had it touched when it
                // stopped" is the question a failed run most needs answered. The message, which
                // may name the document, goes to stderr; the report carries the type and HRESULT.
                log.WriteError("probe drawings stopped.", error);
                sections.Add("probe drawings stopped: " + ProbeText.Failure(error));
                exitCode = ExitError;
            }

            var report = new DrawingProbeReport();
            report.AddRange(DrawingProbeReport.Header(startedAt, swVersion, kind, probeIds));
            report.AddRange(sections);
            report.AddRange(StandardsProbeGateLogLines(observer.Members, observer.Refusals));
            report.Add(DrawingsProbeSeamGateLogLine(seamObserver.Members));
            foreach (string line in report.Lines)
            {
                Out.WriteLine(line);
            }

            try
            {
                Error.WriteLine("Wrote " + report.Write(settings.OutputDirectory, startedAt));
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException
                || error is ArgumentException || error is NotSupportedException)
            {
                log.WriteError("probe drawings could not write its report; the lines above are all of it.", error);
                exitCode = ExitError;
            }
        }

        return exitCode;
    }

    /// <summary>
    /// A part's own Full extraction for D5, D6 and D8 - only when SOLIDWORKS already has it open
    /// (a drawing's models are loaded with it); null otherwise. Asked before the attach, which would
    /// otherwise open it read-only: this run opens nothing it is pointed at, and nothing to compare.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static EvidencePackage? BuildOpenModel(ISldWorks swApp, SwGate gate, string path, DumpOptions options)
    {
        if (!IsOpenDocument(gate, swApp, path))
        {
            return null;
        }

        ISwSession model = SwSession.AttachForDump(swApp, path, null, gate);
        return SwDump.CreateWriter(swApp, model).Build(options);
    }

    /// <summary>
    /// Whether SOLIDWORKS has <paramref name="documentPath"/> open, asked on the gate under the
    /// probe's own member name. The check both read-only probes make before an attach that would
    /// otherwise open a document.
    /// </summary>
    private static bool IsOpenDocument(SwGate gate, ISldWorks swApp, string documentPath) =>
        gate.Call(StandardsProbeMember.OpenDocumentByName, () => swApp.GetOpenDocumentByName(documentPath)) is IModelDoc2;

    /// <summary>Is this one of the subjects <see cref="ProbeSubjects"/> lists?</summary>
    private static bool IsProbeSubject(string subject)
    {
        foreach (string known in ProbeSubjects)
        {
            if (string.Equals(subject, known, StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
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
                ProbeRootComponent(session);
                ProbeComponentTree(session, refs, kind);

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
    /// PROBE-15, the single observation User Story 6 and feature 004 both rest on: what
    /// <c>IConfiguration.GetRootComponent3(false)</c> answers for a PART configuration on
    /// 2024. <see cref="ComponentTreeDumper"/> synthesizes a part root when it answers
    /// nothing (FR-023, RK-15), and that is a claim about this release, so it is printed
    /// rather than believed. The line is written for an assembly too: the same call is the
    /// start of every traversal, and a probe that only printed it in the case under suspicion
    /// would have nothing to compare it against.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeRootComponent(SwSession session)
    {
        SwGate gate = session.Gate;

        Out.WriteLine("root_component: " + Describe(() =>
        {
            object? root = gate.Call(
                "GetRootComponent3", () => session.Configuration.GetRootComponent3(false));

            if (root == null)
            {
                return "(null)";
            }

            // The dumper casts the same way, so an object that is not an IComponent2 is
            // exactly as good as null to it - and very different to whoever reads this.
            if (!(root is IComponent2 component))
            {
                return $"(not IComponent2: {root.GetType().Name})";
            }

            return Quote(gate.Call("Name2", () => component.Name2));
        }));
    }

    /// <summary>
    /// The traversal exactly as the dump performs it - same dumper, same ids - so the
    /// components the probe prints are the ones package.json would carry. For a part opened
    /// alone that is the synthesized part root, including whether SOLIDWORKS gave it a
    /// persistent reference (PROBE-15). For an assembly it is also where the two answers
    /// research R5 could not settle from the signatures appear: what
    /// <c>GetConstrainedStatus</c> reports per component, and whether a mate's feature
    /// reports its suppression.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeComponentTree(SwSession session, PersistRefService refs, DocumentKind kind)
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
                + $" suppression={PackageSerializer.EnumToJsonName(node.Suppression)}"
                + $" persist_ref={(node.PersistRef == null ? "null" : "present")}");
        }

        if (kind == DocumentKind.Assembly)
        {
            ProbeMates(session, refs, scope);
        }

        Out.WriteLine($"gaps: {gaps.Count}");
        foreach (Gap gap in gaps.Gaps)
        {
            Out.WriteLine($"  {gap.EntityKind} {gap.EntityId ?? "-"}: {gap.Reason}");
        }
    }

    /// <summary>The root assembly's mates, through the shipped dumper and the same ids.</summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeMates(SwSession session, PersistRefService refs, DumpScope scope)
    {
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

    // ---- probe standards (T095) ---------------------------------------------------

    /// <summary>
    /// T095. The ten workstation probes of <c>research.md</c> R4, printed in one read-only run
    /// in R4's order (contracts/cli.md row 20). Every question the repository could not settle
    /// offline is here: which interface answers "exploded" and whether the answer is
    /// per-configuration; which appearance slot carries transparency; what a display-state
    /// hide looks like beside a suppression; whether a revision table's cells are reachable
    /// and whether one sheet can carry two tables; whether the type-1 sheet-format pseudo-view
    /// is in <c>GetViews()</c>; whether <c>GetAnnotations()</c> returns what the macro's walk
    /// did; whether a non-active sheet answers at all; which type names the cut-list folders
    /// carry; whether sketch text segments read; and which entity kinds carry a persistent
    /// reference.
    ///
    /// <b>Nothing is opened, activated, rebuilt or written.</b> The document must already be
    /// open, every call goes through a gate built with the read-only guard, and the gate log
    /// printed at the end names every member the run touched - so the claim is checkable
    /// rather than asserted (quickstart scenario 9).
    ///
    /// A probe whose member throws prints the failure and the run carries on: which members
    /// fail on this release is half of what the probe is for.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteProbeStandards(string? documentPath, bool allowStart)
    {
        var observer = new RecordingGateObserver();
        SwGate gate = StandardsProbeGate(observer);
        int exitCode;

        using (var log = new ExtractLog(null))
        {
            try
            {
                ISldWorks swApp = Connect(allowStart, log);

                // SwSession.Attach would OPEN a named document that is not open, read-only -
                // the extractor's one file-opening call. This run opens nothing, so a document
                // that is not open is refused here, before anything else is asked of it.
                if (!string.IsNullOrWhiteSpace(documentPath) && !IsOpenDocument(gate, swApp, documentPath!))
                {
                    throw new InvalidOperationException(
                        StandardsProbeDocumentNotOpenMessage(documentPath!));
                }

                // The extraction's attach (feature 011, contracts/attach.md section 3), so the
                // probe runs on a drawing too, with no configuration; the check above has already
                // refused a document that is not open, so nothing is opened either way.
                ISwSession session = SwSession.AttachForDump(swApp, documentPath, null, gate);
                var refs = new PersistRefService(gate);
                DocumentKind kind = SwSession.KindOf(session.Document, gate);
                var samples = new PersistRefSamples();

                Out.WriteLine("probe: standards - the ten workstation probes of research.md R4");
                Out.WriteLine("document: " + Gated(
                    gate, StandardsProbeMember.PathName, () => Quote(session.Document.GetPathName())));
                Out.WriteLine("kind: " + PackageSerializer.EnumToJsonName(kind));

                // ConfigurationName gates StandardsProbeMember.ConfigurationName itself, so it is
                // described here rather than gated a second time.
                Out.WriteLine("configuration: " + (session.Configuration == null
                    ? "(none: a drawing has no configuration)"
                    : Describe(() => Quote(session.ConfigurationName()))));

                DumpScope scope = StandardsProbeComponents(session, refs);

                ProbeExplodedState(session, gate, scope);
                ProbeAppearanceOverrides(gate, scope);
                ProbeComponentVisibility(gate, scope);
                ProbeDrawing(session, gate, refs, kind, samples);
                ProbeCutListWalk(session, gate, refs, kind, samples);
                ProbeSketchTextSegments(session, gate, refs, kind);
                ProbePersistentReferences(session, gate, refs, samples);

                exitCode = ExitSuccess;
            }
            catch (Exception error)
            {
                // The gate log below still prints: "what had it touched when it stopped" is the
                // question a failed read-only run most needs answered.
                log.WriteError("probe standards stopped.", error);
                exitCode = ExitError;
            }

            foreach (string line in StandardsProbeGateLogLines(observer.Members, observer.Refusals))
            {
                Out.WriteLine(line);
            }
        }

        return exitCode;
    }

    /// <summary>
    /// One instance of each of the seven entity kinds PROBE-10 asks about, kept by the walks
    /// that already hold them so no walk runs a second time.
    /// </summary>
    private sealed class PersistRefSamples
    {
        public object? Sheet { get; set; }

        public object? View { get; set; }

        public object? DisplayDimension { get; set; }

        public object? Annotation { get; set; }

        public object? Note { get; set; }

        public object? RevisionTable { get; set; }

        public object? BodyFolder { get; set; }
    }

    /// <summary>
    /// The four sections one sheet walk fills. PROBE-4, PROBE-5, PROBE-6 and PROBE-7 all read
    /// the same sheets and views, so the drawing is walked once and the lines are printed
    /// afterwards in R4's order: four walks would be four times the interop for one answer,
    /// and on a six-sheet drawing that is the difference the engineer waits for.
    /// </summary>
    private sealed class DrawingProbeLines
    {
        public List<string> Tables { get; } = new List<string>();

        public List<string> Notes { get; } = new List<string>();

        public List<string> Views { get; } = new List<string>();

        public List<string> Sheets { get; } = new List<string>();
    }

    /// <summary>The per-sheet counts PROBE-7 compares; a sheet that came back empty shows up in them.</summary>
    private sealed class SheetCounts
    {
        public int SheetFormatViews { get; set; }

        public int RevisionTables { get; set; }

        public int Annotations { get; set; }

        public int DisplayDimensions { get; set; }

        public int Notes { get; set; }
    }

    /// <summary>
    /// The traversal exactly as the dump performs it - same dumper, same ids - so PROBE-1,
    /// PROBE-2 and PROBE-3 answer about the components package.json would carry. A component
    /// the traversal synthesized (a part root, a drawing's forest root, a referenced model)
    /// has no live <c>IComponent2</c>, and the probes that need one say so rather than
    /// skipping it in silence.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static DumpScope StandardsProbeComponents(ISwSession session, PersistRefService refs)
    {
        var gaps = new GapCollector();
        var options = new DumpOptions { Meshes = MeshFormat.None, Features = FeatureScope.None };
        ComponentTreeResult tree = new ComponentTreeDumper(session, refs).Traverse(gaps, options);
        DumpScope scope = PackageWriter.ScopeFor(gaps, options, tree);

        Out.WriteLine($"components: {scope.Components.Count}, traversal gaps: {gaps.Count}");
        foreach (Gap gap in gaps.Gaps)
        {
            Out.WriteLine($"  {gap.EntityKind} {gap.EntityId ?? "-"}: {gap.Reason}");
        }

        return scope;
    }

    /// <summary>
    /// PROBE-1. Which interface answers "is this assembly exploded", whether the answer is
    /// per-configuration, and whether a sub-assembly's document answers at all.
    ///
    /// The second configuration is read through <c>IConfiguration.GetNumberOfExplodeSteps</c>,
    /// which answers per configuration <b>without activating one</b>: activating a
    /// configuration is a display-state change and a rebuild, the one thing this run may not
    /// do. So the document-level pair answers for the ACTIVE configuration and the step count
    /// answers for every one, and reading the two together is what settles the question.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeExplodedState(ISwSession session, SwGate gate, DumpScope scope)
    {
        Out.WriteLine("probe-1 exploded_state:");
        Out.WriteLine("  open document: " + DescribeExploded(gate, session.Document));
        Out.WriteLine("  configurations (read without activating any):");

        string? failure;
        IReadOnlyList<string> names = ReadList(
            () => ConfigurationNames(gate, session.Document), out failure);

        if (failure != null)
        {
            Out.WriteLine("    GetConfigurationNames: " + failure);
        }

        foreach (string name in names)
        {
            string configuration = name;
            Out.WriteLine($"    {Quote(configuration)} explode_steps=" + Describe(() =>
            {
                var live = gate.Call(
                    StandardsProbeMember.ConfigurationByName,
                    () => session.Document.GetConfigurationByName(configuration)) as IConfiguration;

                return live == null
                    ? "(GetConfigurationByName gave nothing)"
                    : gate.Call(StandardsProbeMember.ExplodeSteps, () => live.GetNumberOfExplodeSteps())
                        .ToString(CultureInfo.InvariantCulture);
            }));
        }

        Out.WriteLine("  sub-assembly documents:");
        int printed = 0;

        foreach (ScopedComponent component in scope.Components)
        {
            ComponentNode node = component.Node;
            if (node.ParentKey == null
                || node.DocumentKind != DocumentKind.Assembly
                || !(node.Handle is IComponent2 live))
            {
                continue;
            }

            printed++;
            Out.WriteLine($"    {component.Id} {node.Key}: " + Describe(() =>
            {
                var model = gate.Call(
                    StandardsProbeMember.ModelDoc2, () => live.GetModelDoc2()) as IModelDoc2;

                return model == null
                    ? "(no loaded document; nothing is opened to produce one)"
                    : DescribeExploded(gate, model);
            }));
        }

        if (printed == 0)
        {
            Out.WriteLine("    (none)");
        }
    }

    /// <summary>The two exploded reads, side by side, for one document.</summary>
    private static string DescribeExploded(SwGate gate, IModelDoc2 document)
    {
        string first = Gated(
            gate, StandardsProbeMember.IsExploded, () => document.IsExploded().ToString());

        string second = Describe(() =>
        {
            string? view = null;
            bool exploded = gate.Call(
                StandardsProbeMember.ExtensionIsExploded,
                () =>
                {
                    string name;
                    bool answer = document.Extension.IsExploded(out name);
                    view = name;
                    return answer;
                });

            return exploded.ToString() + " view=" + Quote(view);
        });

        return $"IModelDoc2.IsExploded()={first} IModelDocExtension.IsExploded(out name)={second}";
    }

    /// <summary>Every configuration name, so the per-configuration read below has a list to walk.</summary>
    private static IReadOnlyList<string> ConfigurationNames(SwGate gate, IModelDoc2 document)
    {
        var names = new List<string>();
        var raw = gate.Call(
            StandardsProbeMember.ConfigurationNames, () => document.GetConfigurationNames()) as object[];

        if (raw == null)
        {
            return names;
        }

        foreach (object item in raw)
        {
            if (item is string text)
            {
                names.Add(text);
            }
        }

        return names;
    }

    /// <summary>
    /// PROBE-2. <c>HasMaterialPropertyValues()</c> and all nine appearance slots for every
    /// component, so the engineer can compare one they have made visibly transparent, one with
    /// an opaque override and one with no override at all.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeAppearanceOverrides(SwGate gate, DumpScope scope)
    {
        Out.WriteLine("probe-2 appearance_overrides:");
        int printed = 0;

        foreach (ScopedComponent component in scope.Components)
        {
            if (!(component.Node.Handle is IComponent2 live))
            {
                continue;
            }

            printed++;
            Out.WriteLine(
                $"  {component.Id} {component.Node.Key}"
                + " HasMaterialPropertyValues=" + Gated(
                    gate,
                    StandardsProbeMember.HasMaterialPropertyValues,
                    () => live.HasMaterialPropertyValues().ToString())
                + " GetMaterialPropertyValues2(1, null)=" + Describe(() => AppearanceSlots(gate, live)));
        }

        if (printed == 0)
        {
            Out.WriteLine("  (no live component on this document)");
        }
    }

    /// <summary>
    /// Every slot verbatim, in order. WHICH slot carries transparency on this build, and which
    /// number means transparent, is what PROBE-2 is asked to settle - so no slot is singled
    /// out and nothing is interpreted here.
    /// </summary>
    private static string AppearanceSlots(SwGate gate, IComponent2 component)
    {
        var values = gate.Call(
            StandardsProbeMember.MaterialPropertyValues,
            () => component.GetMaterialPropertyValues2(
                (int)SolidWorks.Interop.swconst.swInConfigurationOpts_e.swThisConfiguration, null))
            as double[];

        if (values == null)
        {
            return "null";
        }

        var slots = new List<string>(values.Length);
        for (int i = 0; i < values.Length; i++)
        {
            slots.Add($"[{i}]={values[i].ToString("G6", CultureInfo.InvariantCulture)}");
        }

        return $"{values.Length} slots " + string.Join(" ", slots.ToArray());
    }

    /// <summary>
    /// PROBE-3. <c>Visible</c> and <c>GetVisibility(1, null)</c> for every component, with the
    /// suppression state beside them: which read answers "hidden" <b>without</b> conflating
    /// suppression is the question, and it cannot be read off either number alone.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeComponentVisibility(SwGate gate, DumpScope scope)
    {
        Out.WriteLine("probe-3 component_visibility:");
        int printed = 0;

        foreach (ScopedComponent component in scope.Components)
        {
            ComponentNode node = component.Node;
            if (!(node.Handle is IComponent2 live))
            {
                continue;
            }

            printed++;
            Out.WriteLine(
                $"  {component.Id} {node.Key}"
                + " Visible=" + Gated(
                    gate,
                    StandardsProbeMember.Visible,
                    () => live.Visible.ToString(CultureInfo.InvariantCulture))
                + " GetVisibility(1, null)=" + Gated(
                    gate,
                    StandardsProbeMember.Visibility,
                    () => DescribeVisibility(live.GetVisibility(
                        (int)SolidWorks.Interop.swconst.swInConfigurationOpts_e.swThisConfiguration,
                        null)))
                + $" suppression={PackageSerializer.EnumToJsonName(node.Suppression)}");
        }

        if (printed == 0)
        {
            Out.WriteLine("  (no live component on this document)");
        }
    }

    /// <summary>
    /// <c>GetVisibility</c> is declared as returning <c>object</c> and may hand back one value
    /// or one per configuration; both shapes are printed as they came.
    /// </summary>
    private static string DescribeVisibility(object? answer)
    {
        if (answer == null)
        {
            return "null";
        }

        if (answer is Array array)
        {
            var parts = new List<string>(array.Length);
            for (int i = 0; i < array.Length; i++)
            {
                object? item = array.GetValue(i);
                parts.Add(item == null
                    ? "null"
                    : Convert.ToString(item, CultureInfo.InvariantCulture) ?? "null");
            }

            return "[" + string.Join(", ", parts.ToArray()) + "]";
        }

        return Convert.ToString(answer, CultureInfo.InvariantCulture) ?? "null";
    }

    /// <summary>
    /// PROBE-4, PROBE-5, PROBE-6 and PROBE-7: one walk of every sheet, with sheet 1 left
    /// active throughout, printed as four sections in R4's order.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeDrawing(
        ISwSession session,
        SwGate gate,
        PersistRefService refs,
        DocumentKind kind,
        PersistRefSamples samples)
    {
        if (kind != DocumentKind.Drawing)
        {
            WriteDrawingSections("(the open document is not a drawing)");
            return;
        }

        var reader = new SwDrawingReader(session, refs);
        object? drawing = reader.Drawing(session.Document);
        if (drawing == null)
        {
            // The kind read said drawing and the COM cast disagreed. Nothing is opened or
            // activated to resolve it: the probe says so, which is the answer.
            WriteDrawingSections("(the document reports kind drawing but is not an IDrawingDoc)");
            return;
        }

        var lines = new DrawingProbeLines();
        lines.Sheets.Add(
            "  active sheet before the walk: " + Describe(() => Quote(reader.ActiveSheetName(drawing))));

        string? failure;
        IReadOnlyList<string> names = ReadList(() => reader.SheetNames(drawing), out failure);
        if (failure != null)
        {
            lines.Sheets.Add("  GetSheetNames: " + failure);
        }

        foreach (string name in names)
        {
            ProbeSheet(gate, reader, drawing, name, lines, samples);
        }

        // PROBE-7's answer is this pair with the per-sheet counts between them: nothing was
        // activated, so the sheet active before the walk is the sheet active after it.
        lines.Sheets.Add(
            "  active sheet after the walk: " + Describe(() => Quote(reader.ActiveSheetName(drawing))));

        ProbeViewWalkFallback(gate, reader, drawing, lines.Notes);

        WriteSection("probe-4 revision_tables:", lines.Tables);
        WriteSection("probe-5 notes:", lines.Notes);
        WriteSection("probe-6 views_annotations_dimensions:", lines.Views);
        WriteSection("probe-7 non_active_sheets:", lines.Sheets);
    }

    /// <summary>The four drawing sections, each saying the same thing, when there is no drawing to walk.</summary>
    private static void WriteDrawingSections(string reason)
    {
        Out.WriteLine("probe-4 revision_tables: " + reason);
        Out.WriteLine("probe-5 notes: " + reason);
        Out.WriteLine("probe-6 views_annotations_dimensions: " + reason);
        Out.WriteLine("probe-7 non_active_sheets: " + reason);
    }

    private static void WriteSection(string header, IReadOnlyList<string> lines)
    {
        Out.WriteLine(header);
        if (lines.Count == 0)
        {
            Out.WriteLine("  (nothing was read)");
            return;
        }

        foreach (string line in lines)
        {
            Out.WriteLine(line);
        }
    }

    /// <summary>
    /// One sheet, read <b>without activating it</b>: its revision tables, its views' notes,
    /// annotations and display dimensions, and the counts PROBE-7 compares against a second
    /// run in which the engineer activates each sheet by hand first.
    /// </summary>
    private static void ProbeSheet(
        SwGate gate,
        SwDrawingReader reader,
        object drawing,
        string name,
        DrawingProbeLines lines,
        PersistRefSamples samples)
    {
        object? sheet;
        try
        {
            sheet = gate.Call(StandardsProbeMember.Sheet, () => reader.Sheet(drawing, name));
        }
        catch (Exception error)
        {
            AddToEverySection(lines, $"  sheet {Quote(name)}: !{error.GetType().Name}: {error.Message}");
            return;
        }

        if (sheet == null)
        {
            AddToEverySection(lines, $"  sheet {Quote(name)}: (Sheet gave nothing)");
            return;
        }

        if (samples.Sheet == null)
        {
            samples.Sheet = sheet;
        }

        string header = $"  sheet {Quote(name)} GetName="
            + Gated(gate, StandardsProbeMember.Name, () => Quote(reader.SheetName(sheet)));

        lines.Tables.Add(header);
        lines.Notes.Add(header);
        lines.Views.Add(header);

        string? failure;
        IReadOnlyList<object> views = ReadList(
            () => gate.Call(StandardsProbeMember.Views, () => reader.Views(sheet)), out failure);

        if (failure != null)
        {
            lines.Tables.Add("    GetViews: " + failure);
            lines.Notes.Add("    GetViews: " + failure);
            lines.Views.Add("    GetViews: " + failure);
            lines.Sheets.Add($"  sheet {Quote(name)}: GetViews failed, so no count here would be honest");
            return;
        }

        var counts = new SheetCounts();
        ProbeSheetRevisionTables(gate, reader, sheet, views, lines.Tables, counts, samples);

        foreach (object view in views)
        {
            ProbeViewNotes(gate, reader, view, lines.Notes, counts, samples);
            ProbeView(gate, reader, view, lines.Views, counts, samples);
        }

        lines.Sheets.Add(
            $"  sheet {Quote(name)}: views={views.Count}"
            + $" sheet_format_views(Type 1)={counts.SheetFormatViews}"
            + $" tables={counts.RevisionTables} annotations={counts.Annotations}"
            + $" display_dimensions={counts.DisplayDimensions} notes={counts.Notes}");
    }

    private static void AddToEverySection(DrawingProbeLines lines, string line)
    {
        lines.Tables.Add(line);
        lines.Notes.Add(line);
        lines.Views.Add(line);
        lines.Sheets.Add(line);
    }

    /// <summary>
    /// PROBE-4. <c>ISheet.RevisionTable</c> is single-valued and finds at most one table; the
    /// per-view <c>GetTableAnnotations()</c> walk is what would find a second. Both are printed
    /// and counted against each other, because a table the walk misses is a silent miss in a
    /// coverage check rather than an unresolved row.
    /// </summary>
    private static void ProbeSheetRevisionTables(
        SwGate gate,
        SwDrawingReader reader,
        object sheet,
        IReadOnlyList<object> views,
        List<string> output,
        SheetCounts counts,
        PersistRefSamples samples)
    {
        object? fromSheet = null;
        output.Add("    ISheet.RevisionTable: " + Describe(() =>
        {
            fromSheet = gate.Call(
                StandardsProbeMember.RevisionTable, () => reader.SheetRevisionTable(sheet));

            return fromSheet == null ? "(null)" : "present";
        }));

        object? firstFromWalk = null;
        int found = 0;

        foreach (object view in views)
        {
            string? failure;
            IReadOnlyList<object> tables = ReadList(() => reader.TableAnnotations(view), out failure);
            if (failure != null)
            {
                output.Add("    GetTableAnnotations: " + failure);
                continue;
            }

            foreach (object table in tables)
            {
                output.Add($"    table [{found}] ITableAnnotation.Type=" + Gated(
                    gate,
                    StandardsProbeMember.TableType,
                    () => reader.TableAnnotationType(table).ToString(CultureInfo.InvariantCulture)));

                ProbeTableCells(gate, reader, table, output);
                found++;

                if (firstFromWalk == null)
                {
                    firstFromWalk = table;
                }
            }
        }

        counts.RevisionTables = found;
        output.Add(
            $"    tables from the GetTableAnnotations walk: {found}; ISheet.RevisionTable is "
            + $"single-valued and found {(fromSheet == null ? "none" : "one")}");

        if (samples.RevisionTable == null)
        {
            samples.RevisionTable = fromSheet ?? firstFromWalk;
        }
    }

    /// <summary>
    /// The runtime COM cast PROBE-4 asks about and everything it unlocks. An
    /// <c>InvalidCastException</c> here is the whole table's rows lost, so it is reported and
    /// the walk carries on.
    /// </summary>
    private static void ProbeTableCells(
        SwGate gate, SwDrawingReader reader, object table, List<string> output)
    {
        output.Add("      CurrentRevision=" + Gated(
            gate, StandardsProbeMember.CurrentRevision, () => Quote(reader.CurrentRevision(table))));

        RevisionTableShape? shape = null;
        output.Add("      ITableAnnotation cast and counts: " + Describe(() =>
        {
            RevisionTableShape read = reader.TableShape(table);
            shape = read;

            return $"cast ok, RowCount={read.RowCount} ColumnCount={read.ColumnCount} TotalRowCount="
                + Gated(
                    gate,
                    StandardsProbeMember.TotalRowCount,
                    () => ((ITableAnnotation)table).TotalRowCount.ToString(CultureInfo.InvariantCulture));
        }));

        if (shape == null)
        {
            return;
        }

        for (int row = 0; row < shape.Value.RowCount; row++)
        {
            for (int column = 0; column < shape.Value.ColumnCount; column++)
            {
                int r = row;
                int c = column;
                output.Add(
                    $"      cell[{r},{c}] Text=" + Gated(
                        gate, StandardsProbeMember.CellText, () => Quote(reader.Cell(table, r, c)))
                    + " DisplayedText=" + Gated(
                        gate,
                        StandardsProbeMember.CellDisplayedText,
                        () => Quote(((ITableAnnotation)table).DisplayedText[r, c])));
            }
        }
    }

    /// <summary>
    /// PROBE-5. Every note of every view, with the sheet-format pseudo-view marked. Whether a
    /// <c>Type == 1</c> view appears in <c>ISheet.GetViews()</c> at all is what decides whether
    /// FR-024's fall-back enumeration is needed - and whether the export-control check can be
    /// answered for a sheet rather than left unresolved.
    /// </summary>
    private static void ProbeViewNotes(
        SwGate gate,
        SwDrawingReader reader,
        object view,
        List<string> output,
        SheetCounts counts,
        PersistRefSamples samples)
    {
        string type = Gated(
            gate,
            StandardsProbeMember.ViewTypeMember,
            () => reader.ViewType(view).ToString(CultureInfo.InvariantCulture));

        bool isSheetFormat = type == "1";
        if (isSheetFormat)
        {
            counts.SheetFormatViews++;
        }

        output.Add(
            "    view " + Gated(gate, StandardsProbeMember.ViewName, () => Quote(reader.ViewName(view)))
            + $" Type={type}" + (isSheetFormat ? "  <- the sheet-format pseudo-view" : string.Empty));

        string? failure;
        IReadOnlyList<object> notes = ReadList(
            () => gate.Call(StandardsProbeMember.Notes, () => reader.Notes(view)), out failure);

        if (failure != null)
        {
            output.Add("      GetNotes: " + failure);
            return;
        }

        counts.Notes += notes.Count;
        output.Add($"      notes: {notes.Count}");

        foreach (object note in notes)
        {
            if (samples.Note == null)
            {
                samples.Note = note;
            }

            output.Add("        " + Gated(
                gate, StandardsProbeMember.NoteText, () => Quote(reader.NoteText(note))));
        }
    }

    /// <summary>
    /// PROBE-6. Per view: the type, the referenced model, whether its document handle is
    /// non-null - nothing is opened or loaded to make it so - and then every annotation and
    /// every display dimension.
    /// </summary>
    private static void ProbeView(
        SwGate gate,
        SwDrawingReader reader,
        object view,
        List<string> output,
        SheetCounts counts,
        PersistRefSamples samples)
    {
        if (samples.View == null)
        {
            samples.View = view;
        }

        output.Add(
            "    view " + Gated(gate, StandardsProbeMember.ViewName, () => Quote(reader.ViewName(view)))
            + " Type=" + Gated(
                gate,
                StandardsProbeMember.ViewTypeMember,
                () => reader.ViewType(view).ToString(CultureInfo.InvariantCulture))
            + " GetReferencedModelName=" + Gated(
                gate,
                StandardsProbeMember.ReferencedModelName,
                () => Quote(reader.ReferencedModelPath(view)))
            + " ReferencedDocument=" + Describe(() =>
            {
                object? referenced = gate.Call(
                    StandardsProbeMember.ReferencedDocument, () => reader.ReferencedDocument(view));

                return referenced == null
                    ? "null (the model is not loaded; nothing is opened to load it)"
                    : "non-null, GetPathName=" + Gated(
                        gate, StandardsProbeMember.PathName, () => Quote(reader.DocumentPath(referenced)));
            }));

        ProbeViewAnnotations(gate, reader, view, output, counts, samples);
        ProbeViewDimensions(gate, reader, view, output, counts, samples);
    }

    /// <summary>
    /// <c>GetAnnotations()</c> against <c>GetAnnotationCount()</c> and the macro's own
    /// <c>GetFirstAnnotation3</c>/<c>GetNext3</c> walk. A set from <c>GetAnnotations()</c>
    /// smaller than the walk's is a silent under-report rather than an unresolved row, which
    /// is exactly what SC-016's per-(check, document) parity would hide - so the names and
    /// types on either side are listed rather than counted.
    /// </summary>
    private static void ProbeViewAnnotations(
        SwGate gate,
        SwDrawingReader reader,
        object view,
        List<string> output,
        SheetCounts counts,
        PersistRefSamples samples)
    {
        string? failure;
        IReadOnlyList<object> fromGetAnnotations = ReadList(
            () => gate.Call(StandardsProbeMember.Annotations, () => reader.Annotations(view)), out failure);

        if (failure != null)
        {
            output.Add("      GetAnnotations: " + failure);
            return;
        }

        string count = Gated(
            gate,
            StandardsProbeMember.AnnotationCount,
            () => ((IView)view).GetAnnotationCount().ToString(CultureInfo.InvariantCulture));

        string? walkFailure;
        IReadOnlyList<object> fromWalk = ReadList(() => AnnotationWalk(gate, view), out walkFailure);

        counts.Annotations += fromGetAnnotations.Count;
        output.Add(
            $"      annotations: GetAnnotations()={fromGetAnnotations.Count} GetAnnotationCount()={count}"
            + " GetFirstAnnotation3/GetNext3 walk="
            + (walkFailure ?? fromWalk.Count.ToString(CultureInfo.InvariantCulture)));

        foreach (object annotation in fromGetAnnotations)
        {
            if (samples.Annotation == null)
            {
                samples.Annotation = annotation;
            }

            output.Add("        " + DescribeAnnotation(gate, reader, annotation));
        }

        if (walkFailure != null)
        {
            return;
        }

        output.Add("        only in GetAnnotations(): "
            + MissingAnnotations(gate, reader, fromGetAnnotations, fromWalk));
        output.Add("        only in the GetFirstAnnotation3 walk: "
            + MissingAnnotations(gate, reader, fromWalk, fromGetAnnotations));
    }

    /// <summary>The macro's own annotation enumeration, bounded the way every walk here is.</summary>
    private static IReadOnlyList<object> AnnotationWalk(SwGate gate, object view)
    {
        var walked = new List<object>();
        var current = gate.Call(
            StandardsProbeMember.FirstAnnotation,
            () => ((IView)view).GetFirstAnnotation3()) as IAnnotation;

        while (current != null && walked.Count < StandardsProbeMaxWalk)
        {
            IAnnotation annotation = current;
            walked.Add(annotation);
            current = gate.Call(
                StandardsProbeMember.NextAnnotation, () => annotation.GetNext3()) as IAnnotation;
        }

        return walked;
    }

    private static string DescribeAnnotation(SwGate gate, SwDrawingReader reader, object annotation) =>
        "name=" + AnnotationName(gate, reader, annotation)
        + " type=" + AnnotationType(gate, reader, annotation)
        + " dangling=" + Gated(
            gate, StandardsProbeMember.Dangling, () => reader.IsDangling(annotation).ToString());

    private static string AnnotationName(SwGate gate, SwDrawingReader reader, object annotation) =>
        Gated(gate, StandardsProbeMember.Name, () => Quote(reader.AnnotationName(annotation)));

    private static string AnnotationType(SwGate gate, SwDrawingReader reader, object annotation) =>
        Gated(
            gate,
            StandardsProbeMember.AnnotationType,
            () => reader.AnnotationType(annotation).ToString(CultureInfo.InvariantCulture));

    /// <summary>
    /// The annotations of <paramref name="left"/> whose name no annotation of
    /// <paramref name="right"/> carries, as name and type.
    /// </summary>
    private static string MissingAnnotations(
        SwGate gate,
        SwDrawingReader reader,
        IReadOnlyList<object> left,
        IReadOnlyList<object> right)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (object annotation in right)
        {
            names.Add(AnnotationName(gate, reader, annotation));
        }

        var missing = new List<string>();
        foreach (object annotation in left)
        {
            string name = AnnotationName(gate, reader, annotation);
            if (!names.Contains(name))
            {
                missing.Add(name + " type=" + AnnotationType(gate, reader, annotation));
            }
        }

        return Listed(missing);
    }

    /// <summary>
    /// Every display dimension's override flag, override value, type and computed value. The
    /// computed value is in metres; whether the override value is reported in the same unit is
    /// exactly what PROBE-6 is asked to settle, so both are printed raw and neither is
    /// converted.
    /// </summary>
    private static void ProbeViewDimensions(
        SwGate gate,
        SwDrawingReader reader,
        object view,
        List<string> output,
        SheetCounts counts,
        PersistRefSamples samples)
    {
        string? failure;
        IReadOnlyList<object> dimensions = ReadList(
            () => gate.Call(StandardsProbeMember.DisplayDimensions, () => reader.DisplayDimensions(view)),
            out failure);

        if (failure != null)
        {
            output.Add("      GetDisplayDimensions: " + failure);
            return;
        }

        counts.DisplayDimensions += dimensions.Count;
        output.Add($"      display dimensions: {dimensions.Count}");

        foreach (object dimension in dimensions)
        {
            if (samples.DisplayDimension == null)
            {
                samples.DisplayDimension = dimension;
            }

            output.Add(
                "        name=" + Describe(() => Quote(reader.DimensionName(dimension)))
                + " Type2=" + Gated(
                    gate,
                    StandardsProbeMember.DimensionType,
                    () => reader.DimensionType(dimension).ToString(CultureInfo.InvariantCulture))
                + " GetOverride=" + Gated(
                    gate, StandardsProbeMember.Override, () => reader.IsOverridden(dimension).ToString())
                + " GetOverrideValue=" + Gated(
                    gate,
                    StandardsProbeMember.OverrideValue,
                    () => reader.OverrideValue(dimension).ToString("G17", CultureInfo.InvariantCulture))
                + " GetSystemValue3=" + Describe(
                    () => reader.DimensionValue(dimension).ToString("G17", CultureInfo.InvariantCulture)));
        }
    }

    /// <summary>
    /// PROBE-5's comparison: the <c>IDrawingDoc.GetFirstView()</c> / <c>IView.GetNextView()</c>
    /// enumeration, which crosses every sheet without activating one. If the type-1
    /// sheet-format pseudo-view is missing from <c>ISheet.GetViews()</c> and present here, the
    /// fall-back enumeration is needed; if it is in neither, the export-control check is
    /// unresolved for that sheet and this run is the reason it is.
    /// </summary>
    private static void ProbeViewWalkFallback(
        SwGate gate, SwDrawingReader reader, object drawing, List<string> output)
    {
        output.Add("  GetFirstView()/GetNextView() walk (every sheet, nothing activated):");

        object? current;
        try
        {
            current = gate.Call(
                StandardsProbeMember.FirstView, () => ((IDrawingDoc)drawing).GetFirstView());
        }
        catch (Exception error)
        {
            output.Add($"    !{error.GetType().Name}: {error.Message}");
            return;
        }

        int index = 0;
        while (current != null && index < StandardsProbeMaxWalk)
        {
            object view = current;
            output.Add(
                $"    [{index}] name=" + Gated(
                    gate, StandardsProbeMember.ViewName, () => Quote(reader.ViewName(view)))
                + " Type=" + Gated(
                    gate,
                    StandardsProbeMember.ViewTypeMember,
                    () => reader.ViewType(view).ToString(CultureInfo.InvariantCulture)));

            index++;
            try
            {
                current = gate.Call(
                    StandardsProbeMember.NextView, () => ((IView)view).GetNextView());
            }
            catch (Exception error)
            {
                output.Add($"    !{error.GetType().Name}: {error.Message}");
                return;
            }
        }
    }

    /// <summary>
    /// PROBE-8. Every feature's <c>GetTypeName2</c> and <c>Name</c> at every depth, with the
    /// <c>GetSpecificFeature2</c> object type, the body count and the exclusion flag for each
    /// body folder - which is what settles the type names the cut-list folders carry on this
    /// release, and whether the exclusion flag reads without activating a folder.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeCutListWalk(
        ISwSession session,
        SwGate gate,
        PersistRefService refs,
        DocumentKind kind,
        PersistRefSamples samples)
    {
        Out.WriteLine("probe-8 cut_list_walk:");
        if (kind == DocumentKind.Drawing)
        {
            Out.WriteLine(
                "  (the open document is a drawing; run this on the weldment or sheet-metal part)");
            return;
        }

        var reader = new SwCutListReader(gate, refs);
        string? failure;
        IReadOnlyList<object> features = ReadList(() => reader.Features(session.Document), out failure);

        if (failure != null)
        {
            Out.WriteLine("  FirstFeature walk: " + failure);
            return;
        }

        Out.WriteLine($"  features: {features.Count}");
        foreach (object feature in features)
        {
            ProbeCutListFeature(gate, reader, feature, 0, samples);
        }
    }

    private static void ProbeCutListFeature(
        SwGate gate, SwCutListReader reader, object feature, int depth, PersistRefSamples samples)
    {
        string indent = new string(' ', 4 + (depth * 2));
        object? folder = null;

        string specific = Describe(() =>
        {
            folder = gate.Call(StandardsProbeMember.SpecificFeature, () => reader.BodyFolder(feature));
            return folder == null ? "(not an IBodyFolder)" : "IBodyFolder";
        });

        string bodies = "-";
        string excluded = "-";
        if (folder != null)
        {
            object bodyFolder = folder;
            bodies = Gated(
                gate,
                StandardsProbeMember.BodyCount,
                () => reader.BodyCount(bodyFolder).ToString(CultureInfo.InvariantCulture));

            excluded = Gated(
                gate,
                StandardsProbeMember.ExcludeFromCutList,
                () => reader.ExcludedFromCutList(feature).ToString());

            if (samples.BodyFolder == null)
            {
                // The persistent reference is asked for the FEATURE, which is what a cut-list
                // item's subject is; the body folder is only how it was identified.
                samples.BodyFolder = feature;
            }
        }

        Out.WriteLine(
            $"{indent}depth={depth}"
            + " type_name=" + Gated(
                gate, StandardsProbeMember.TypeName, () => Quote(reader.TypeName(feature)))
            + " name=" + Gated(
                gate, StandardsProbeMember.FeatureName, () => Quote(reader.Name(feature)))
            + $" GetSpecificFeature2={specific} bodies={bodies} ExcludeFromCutList={excluded}");

        if (depth >= StandardsProbeMaxDepth)
        {
            Out.WriteLine($"{indent}  (deeper sub-features not walked)");
            return;
        }

        string? failure;
        IReadOnlyList<object> children = ReadList(() => reader.SubFeatures(feature), out failure);
        if (failure != null)
        {
            Out.WriteLine($"{indent}  GetFirstSubFeature: " + failure);
            return;
        }

        foreach (object child in children)
        {
            ProbeCutListFeature(gate, reader, child, depth + 1, samples);
        }
    }

    /// <summary>
    /// PROBE-9. <c>GetSketchTextSegments()</c> for every sketch in the tree, sub-features
    /// included - which is where a hole-wizard's sketch lives - printing null, empty and a
    /// length distinctly, because telling those three apart is the whole question.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbeSketchTextSegments(
        ISwSession session, SwGate gate, PersistRefService refs, DocumentKind kind)
    {
        Out.WriteLine("probe-9 sketch_text_segments:");
        if (kind == DocumentKind.Drawing)
        {
            Out.WriteLine("  (the open document is a drawing; run this on the part carrying the sketches)");
            return;
        }

        var reader = new SwFeatureReader(gate, refs);
        string? failure;
        IReadOnlyList<FeatureTreeNode> walk = ReadList(() => reader.Walk(session.Document), out failure);

        if (failure != null)
        {
            Out.WriteLine("  FirstFeature walk: " + failure);
            return;
        }

        IReadOnlyList<FeatureTreeRow> rows = FeatureTreeIndexer.Index(walk, new IdAllocator("feat"));
        int printed = 0;

        foreach (FeatureTreeRow row in rows)
        {
            object? handle = row.Node.Handle;
            if (handle == null)
            {
                continue;
            }

            object? sketch;
            try
            {
                sketch = gate.Call(StandardsProbeMember.SpecificFeature, () => reader.Sketch(handle));
            }
            catch (Exception error)
            {
                Out.WriteLine($"  {row.Id} GetSpecificFeature2: !{error.GetType().Name}: {error.Message}");
                continue;
            }

            if (sketch == null)
            {
                continue;
            }

            object live = sketch;
            printed++;
            Out.WriteLine(
                $"  {row.Id} depth={row.Depth} type_name={Quote(row.Node.TypeName)}"
                + $" name={Quote(row.Node.Name)} GetSketchTextSegments=" + Gated(
                    gate,
                    StandardsProbeMember.SketchTextSegments,
                    () => DescribeSegments(reader.SketchTextSegments(live))));
        }

        if (printed == 0)
        {
            Out.WriteLine("  (no sketch in the feature tree)");
        }
    }

    /// <summary>null, empty and a length, told apart - which is what PROBE-9 asks.</summary>
    private static string DescribeSegments(object? segments)
    {
        if (segments == null)
        {
            return "null";
        }

        if (segments is Array array)
        {
            return array.Length == 0
                ? "empty (a zero-length array)"
                : array.Length.ToString(CultureInfo.InvariantCulture) + " segment(s)";
        }

        return $"(not an array: {segments.GetType().Name})";
    }

    /// <summary>
    /// PROBE-10. <c>GetPersistReference3</c> and <c>GetPersistReferenceCount3</c> for one
    /// instance of each of the seven entity kinds schema 1.4.0 added. Which kinds SOLIDWORKS
    /// answers for decides which finding subjects the page renders a Show control for
    /// (FR-026, FR-031), so a kind with no instance on this document says that rather than
    /// reading as a refusal.
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void ProbePersistentReferences(
        ISwSession session, SwGate gate, PersistRefService refs, PersistRefSamples samples)
    {
        Out.WriteLine("probe-10 persistent_references:");
        ProbePersistentReference(session, gate, refs, "sheet", samples.Sheet);
        ProbePersistentReference(session, gate, refs, "view", samples.View);
        ProbePersistentReference(session, gate, refs, "display_dimension", samples.DisplayDimension);
        ProbePersistentReference(session, gate, refs, "annotation", samples.Annotation);
        ProbePersistentReference(session, gate, refs, "note", samples.Note);
        ProbePersistentReference(session, gate, refs, "revision_table", samples.RevisionTable);
        ProbePersistentReference(session, gate, refs, "cut_list_item", samples.BodyFolder);
    }

    private static void ProbePersistentReference(
        ISwSession session, SwGate gate, PersistRefService refs, string kind, object? entity)
    {
        if (entity == null)
        {
            Out.WriteLine($"  {kind}: (no instance on this document)");
            return;
        }

        object live = entity;
        Out.WriteLine($"  {kind}: " + Describe(() =>
        {
            ScopedPersistRef? reference = refs.TryGet(session.Document, live);
            string count = Gated(
                gate,
                StandardsProbeMember.PersistReferenceCount,
                () => session.Document.Extension.GetPersistReferenceCount3(live)
                    .ToString(CultureInfo.InvariantCulture));

            return reference == null
                ? $"GetPersistReference3 gave none, GetPersistReferenceCount3={count}"
                : $"{Convert.FromBase64String(reference.Base64).Length} bytes, "
                    + $"GetPersistReferenceCount3={count}";
        }));
    }

    /// <summary>
    /// One probe reading that produces a list. A member that throws yields an empty list and
    /// the failure text, so the caller puts the failure in the section it belongs to and the
    /// walk carries on: which members fail on this release is half of what the probe is for.
    /// </summary>
    private static IReadOnlyList<T> ReadList<T>(Func<IReadOnlyList<T>> read, out string? failure)
    {
        try
        {
            failure = null;
            return read();
        }
        catch (Exception error)
        {
            failure = $"!{error.GetType().Name}: {error.Message}";
            return new T[0];
        }
    }

    /// <summary>
    /// T055. The engineer-run suppressibility test: the only command in the product that
    /// changes the model (contracts/cli.md, research R6). Not reachable from the add-in, the
    /// bridge or the MCP toolset - this method is the whole surface.
    /// </summary>
    internal static int RunSuppressTest(string[] args)
    {
        CommandLine parsed;
        SuppressTestSettings settings;
        string documentPath;
        string outputDirectory;
        bool allowStart;

        try
        {
            parsed = CommandLine.Parse(args, 1, KnownOptions(SuppressTestOptionNames));
            allowStart = parsed.Flag("allow-start");
            documentPath = parsed.Required("doc");
            outputDirectory = parsed.Required("out");
            settings = SuppressTestSettingsFrom(parsed);
        }
        catch (UsageError error)
        {
            Error.WriteLine($"swreview-extract suppress-test: {error.Message}");
            return ExitError;
        }

        // The first refusal contracts/cli.md lists, and the only one that can be made without
        // SOLIDWORKS - so it is made here, before Connect attaches to (or starts) the
        // engineer's session. SuppressTest.Run refuses with the same sentence for any other
        // caller; this is what keeps "refuses, before touching anything" literally true.
        if (!settings.Acknowledged)
        {
            Error.WriteLine($"swreview-extract suppress-test: {SuppressTest.AcknowledgementRequiredMessage}");
            return ExitError;
        }

        return ExecuteSuppressTest(documentPath, outputDirectory, settings, allowStart);
    }

    /// <summary>
    /// The command line as the run settings, defaults included. Shared with the option tests,
    /// which assert against THIS method rather than a copy of the defaults.
    /// </summary>
    internal static SuppressTestSettings SuppressTestSettingsFrom(CommandLine parsed)
    {
        if (parsed == null)
        {
            throw new ArgumentNullException(nameof(parsed));
        }

        var settings = new SuppressTestSettings
        {
            PlanFile = parsed.Required("plan"),
            Acknowledged = parsed.Flag("acknowledge-rebuild"),
            Limit = parsed.Int("limit") ?? SuppressTestSettings.DefaultLimit,
            TimeoutSeconds = parsed.Int("timeout-seconds") ?? SuppressTestSettings.DefaultTimeoutSeconds,
        };

        if (settings.Limit < 1)
        {
            throw new UsageError("--limit must be at least 1.");
        }

        if (settings.TimeoutSeconds < 1)
        {
            throw new UsageError("--timeout-seconds must be at least 1.");
        }

        return settings;
    }

    /// <summary>
    /// The one gate in the product built with <see cref="SuppressTestGuard"/>: the read-only
    /// guard minus <c>SetSuppression2</c> and <c>ForceRebuild3</c>, watched by a recorder so
    /// the distinct member names reach <c>suppress-test.log</c> (SC-003, research R6).
    /// </summary>
    internal static SwGate SuppressTestGate(RecordingGateObserver observer) =>
        new SwGate(new CircuitBreaker(), new SuppressTestGuard()) { Observer = observer };

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int ExecuteSuppressTest(
        string documentPath,
        string outputDirectory,
        SuppressTestSettings settings,
        bool allowStart)
    {
        var observer = new RecordingGateObserver();

        using (var log = new ExtractLog(outputDirectory, SuppressTestLogFileName))
        {
            try
            {
                log.Write($"suppress-test --doc \"{documentPath}\" --plan \"{settings.PlanFile}\" "
                    + $"--out \"{outputDirectory}\" --limit {settings.Limit} "
                    + $"--timeout-seconds {settings.TimeoutSeconds}");

                // Both are read before SOLIDWORKS is touched: a missing plan or package is a
                // usage mistake, and learning that after a two-second attach helps nobody.
                SuppressPlan plan = SuppressPlan.Load(settings.PlanFile);
                EvidencePackage package = PackageAppender.Load(outputDirectory);

                ISldWorks swApp = Connect(allowStart, log);
                SwGate gate = SuppressTestGate(observer);

                // The document must ALREADY be open. SwSession.Attach would otherwise open it
                // through the extractor's one open path, which is read-only and silent - and a
                // read-only document answers false to every SetSuppression2, so the run would
                // record not_applied for every planned feature and prove nothing, having
                // opened the engineer's part to do it.
                if (!(gate.Call("GetOpenDocumentByName", () => swApp.GetOpenDocumentByName(documentPath))
                        is IModelDoc2))
                {
                    throw new SuppressTestRefusedError(SuppressTest.DocumentNotOpenMessage(documentPath));
                }

                // The configuration is NOT asked for here: SuppressTest compares the active
                // one with the plan's and refuses with the message the contract names.
                SwSession session = SwSession.Attach(swApp, documentPath, null, gate);
                log.Write($"Document: {session.DocumentPath} [{session.Configuration.Name}]");

                var target = new SwSuppressTarget(gate, session.Document, new PersistRefService(gate));
                SuppressTestResult result = new SuppressTest(gate, target).Run(
                    plan, package.Features, settings);

                string path = PackageAppender.AppendSuppressTest(outputDirectory, result.Run);

                foreach (string line in SuppressTest.LogLines(result, observer.Members))
                {
                    log.Write(line);
                }

                log.Write($"Wrote {path}");
                Out.WriteLine(path);
                Out.WriteLine(SuppressTest.ModifiedInMemoryMessage);
                return result.Succeeded ? ExitSuccess : ExitError;
            }
            catch (SuppressTestRefusedError refusal)
            {
                // A refusal happens before the first mutation, so the document is untouched
                // and there is nothing to tell the engineer to close.
                log.WriteError("suppress-test refused, and nothing was changed.", refusal);
                return ExitError;
            }
            catch (Exception error)
            {
                log.WriteError("suppress-test failed.", error);
                log.Write("Interop members seen: " + string.Join(", ", observer.Members));
                Out.WriteLine(SuppressTest.ModifiedInMemoryMessage);
                return ExitError;
            }
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
        writer.WriteLine("                --features tree|none --equations on|off");
        writer.WriteLine("                --profile full|model-check|standards");
        writer.WriteLine("                Write package.json and meshes/ for the active or named document.");
        writer.WriteLine("                --profile model-check reads documents, mates, features and");
        writer.WriteLine("                equations only: no holes, fasteners, faces or meshes.");
        writer.WriteLine("                --profile standards reads those five plus the cut list, and the");
        writer.WriteLine("                drawing sheets when the document is a drawing. The package");
        writer.WriteLine("                records which profile wrote it as extractor.profile, and every");
        writer.WriteLine("                phase as extractor.phases whether it ran or not - which is what");
        writer.WriteLine("                a consumer decides a partial extract from, not the name.");
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
        writer.WriteLine("                equations and fillet data for one document, what");
        writer.WriteLine("                GetRootComponent3 returned, the components the traversal");
        writer.WriteLine("                produced, and for an assembly its mates and their");
        writer.WriteLine("                suppression. Writes nothing.");
        writer.WriteLine("  probe standards  [--doc <path>]");
        writer.WriteLine("                Print the ten workstation probes: the exploded reads, the nine");
        writer.WriteLine("                appearance slots and both visibility reads per component, the");
        writer.WriteLine("                revision tables, notes, views, annotations and dimensions of");
        writer.WriteLine("                every sheet with sheet 1 left active, the cut-list walk, the");
        writer.WriteLine("                sketch text segments, and the persistent references of the");
        writer.WriteLine("                seven new entity kinds. The document must already be open:");
        writer.WriteLine("                this run opens nothing, activates no sheet and changes no");
        writer.WriteLine("                display state, and prints its own gate log to prove it.");
        writer.WriteLine("                Writes nothing.");
        writer.WriteLine("  probe drawings --out <dir> [--doc <path>] [--probe D1,D2,...]");
        writer.WriteLine("                Print the feature 011 drawing probes D1 to D14 (default: every");
        writer.WriteLine("                one that applies to the open document's kind, except D14) as");
        writer.WriteLine("                ids, counts, member answers and millimetres - never a name,");
        writer.WriteLine("                path or value - and write the same report to");
        writer.WriteLine("                drawings-probe-<UTC time>.txt in --out. Read-only on the");
        writer.WriteLine("                read-only guard; the document must already be open. D14, run");
        writer.WriteLine("                only when named beside a part or assembly, opens the");
        writer.WriteLine("                same-name drawing read-only and hidden through the confirmed");
        writer.WriteLine("                open's own guard, reads it and closes it again.");
        writer.WriteLine("  probe remodel [--probe <id,...>] --out <dir> [--keep-part]");
        writer.WriteLine("                --acknowledge-throwaway-part");
        writer.WriteLine("                Build a throwaway part in --out and run the selected feature 004");
        writer.WriteLine("                Phase 2 probes against it (default: every probe). Refuses without");
        writer.WriteLine("                the flag and while any document is open in SOLIDWORKS - it never");
        writer.WriteLine("                touches a document you have open. Writes");
        writer.WriteLine("                capabilities/remodel-<sw-version>.yaml with one verdict per probe");
        writer.WriteLine("                (verified, refuted or unresolved) and deletes the throwaway part");
        writer.WriteLine("                afterwards unless --keep-part is given.");
        writer.WriteLine("  suppress-test --doc <part> --plan <suppress-plan.json> --acknowledge-rebuild");
        writer.WriteLine("                --out <package dir> [--limit <n>] [--timeout-seconds <n>]");
        writer.WriteLine("                Suppress each planned Detail feature in turn, rebuild, record");
        writer.WriteLine("                what breaks, and restore the tree. THIS MODIFIES THE OPEN");
        writer.WriteLine("                DOCUMENT IN MEMORY; it never saves, and you close it without");
        writer.WriteLine("                saving afterwards. Run it on a part you chose, not on work in");
        writer.WriteLine("                progress. Write the plan with 'swreview rms suppress-plan'.");
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
