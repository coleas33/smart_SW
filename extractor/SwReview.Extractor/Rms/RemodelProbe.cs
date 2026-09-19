using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// Raised when <c>probe remodel</c> refuses to run. Every one of these is checked before the
/// throwaway part is built, so a refused run leaves nothing behind (tasks.md Phase 2).
/// </summary>
[Serializable]
public class RemodelProbeRefusedError : Exception
{
    public RemodelProbeRefusedError(string message)
        : base(message)
    {
    }
}

/// <summary>
/// One row's answer: a probe either settled the question one way or the other, or it did not
/// (T031). <c>Unresolved</c> is also what a probe that threw records - never
/// <see cref="Verified"/> - and it is what a probe records of itself when its own reading is
/// genuinely ambiguous (research.md's PROBE-11: "unknown gives unresolved").
/// </summary>
public enum RemodelProbeVerdict
{
    Verified,
    Refuted,
    Unresolved,
}

/// <summary>The command-line and ledger spelling of a <see cref="RemodelProbeVerdict"/>.</summary>
public static class RemodelProbeVerdicts
{
    public static string CliName(this RemodelProbeVerdict verdict)
    {
        switch (verdict)
        {
            case RemodelProbeVerdict.Verified:
                return "verified";
            case RemodelProbeVerdict.Refuted:
                return "refuted";
            case RemodelProbeVerdict.Unresolved:
                return "unresolved";
            default:
                throw new ArgumentOutOfRangeException(nameof(verdict), verdict, "Unknown remodel probe verdict.");
        }
    }
}

/// <summary>
/// The seven kinds of step <see cref="RemodelProbePartRecipe.Default"/> composes. Every kind
/// but <see cref="Folder"/> and <see cref="Equation"/> is a solid-body feature; those two carry
/// the extra data (<see cref="RemodelProbeFeatureStep.FolderMembers"/> and
/// <see cref="RemodelProbeFeatureStep.EquationText"/>) the others do not need.
/// </summary>
public enum RemodelProbeFeatureKind
{
    Box,
    Cut,
    Fillet,
    Chamfer,
    Shell,
    Folder,
    Equation,
}

/// <summary>
/// One step of the throwaway-part recipe: the name it is given and what kind of feature it is.
/// Pure data - no interop type anywhere in this class - so the recipe is exactly as testable
/// as <see cref="RemodelProbePartRecipe.Default"/> promises (T031).
/// </summary>
public sealed class RemodelProbeFeatureStep
{
    public RemodelProbeFeatureStep(
        string name,
        RemodelProbeFeatureKind kind,
        IReadOnlyList<string>? folderMembers = null,
        string? equationText = null)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            throw new ArgumentException("A recipe step needs a name.", nameof(name));
        }

        if (kind == RemodelProbeFeatureKind.Folder && (folderMembers == null || folderMembers.Count == 0))
        {
            throw new ArgumentException(
                "A folder step names the steps it contains.", nameof(folderMembers));
        }

        if (kind == RemodelProbeFeatureKind.Equation && string.IsNullOrWhiteSpace(equationText))
        {
            throw new ArgumentException(
                "An equation step names its equation text.", nameof(equationText));
        }

        Name = name;
        Kind = kind;
        FolderMembers = folderMembers ?? Array.Empty<string>();
        EquationText = equationText;
    }

    /// <summary>The name this step's feature is given after it is created.</summary>
    public string Name { get; }

    public RemodelProbeFeatureKind Kind { get; }

    /// <summary>
    /// Only for <see cref="RemodelProbeFeatureKind.Folder"/>: the prior steps' names the
    /// folder wraps, in the contiguous order they were created (PROBE-4's precondition).
    /// </summary>
    public IReadOnlyList<string> FolderMembers { get; }

    /// <summary>Only for <see cref="RemodelProbeFeatureKind.Equation"/>: the equation text.</summary>
    public string? EquationText { get; }
}

/// <summary>
/// T031. The throwaway-part recipe: pure data describing what <c>probe remodel</c> builds
/// before it runs a single probe, so the recipe itself - what it contains, what order it is
/// in, which two features deliberately share a name - is testable with no SOLIDWORKS seat.
/// <see cref="SwRemodelProbeHost"/> is what turns this into interop calls; nothing in this
/// class knows that host exists.
/// </summary>
public sealed class RemodelProbePartRecipe
{
    public RemodelProbePartRecipe(IReadOnlyList<RemodelProbeFeatureStep> steps)
    {
        if (steps == null || steps.Count == 0)
        {
            throw new ArgumentException("A recipe needs at least one step.", nameof(steps));
        }

        Steps = steps;
    }

    public IReadOnlyList<RemodelProbeFeatureStep> Steps { get; }

    /// <summary>
    /// The one recipe every stage-1 probe run builds (research.md R10, tasks.md T031): a box,
    /// a cut, a fillet, a chamfer, a shell, one folder wrapping the box and the cut - the
    /// first two steps, so the run they wrap is contiguous by construction (PROBE-4) - one
    /// global equation reading <c>"w" = 120</c> verbatim (PROBE-2's exact wording), and two
    /// features - the fillet and the chamfer - deliberately given the same name, because a
    /// tree with a genuine duplicate name is exactly what PROBE-3's reorder, PROBE-4's folder
    /// and PROBE-11's type census must be measured against rather than assumed to survive.
    /// </summary>
    public static RemodelProbePartRecipe Default()
    {
        const string boxName = "Boss-Extrude1";
        const string cutName = "Cut-Extrude1";
        const string duplicateName = "Fillet1";

        return new RemodelProbePartRecipe(new[]
        {
            new RemodelProbeFeatureStep(boxName, RemodelProbeFeatureKind.Box),
            new RemodelProbeFeatureStep(cutName, RemodelProbeFeatureKind.Cut),
            new RemodelProbeFeatureStep(duplicateName, RemodelProbeFeatureKind.Fillet),
            new RemodelProbeFeatureStep(duplicateName, RemodelProbeFeatureKind.Chamfer),
            new RemodelProbeFeatureStep("Shell1", RemodelProbeFeatureKind.Shell),
            new RemodelProbeFeatureStep(
                "Folder1", RemodelProbeFeatureKind.Folder, folderMembers: new[] { boxName, cutName }),
            new RemodelProbeFeatureStep(
                "w", RemodelProbeFeatureKind.Equation, equationText: "\"w\" = 120"),
        });
    }
}

/// <summary>
/// One probe's fixed metadata from the research backlog (research.md R10, quickstart.md
/// Scenario 4): the question it answers, the method it uses, whether it gates the write code
/// in Phases 3 to 6, and what a bad or unresolved answer costs. None of this varies run to
/// run, which is why it is data and not a delegate.
/// </summary>
public sealed class RemodelProbeDefinition
{
    public RemodelProbeDefinition(string id, string question, string method, bool blocking, string fallback)
    {
        Id = id ?? throw new ArgumentNullException(nameof(id));
        Question = question ?? throw new ArgumentNullException(nameof(question));
        Method = method ?? throw new ArgumentNullException(nameof(method));
        Blocking = blocking;
        Fallback = fallback ?? throw new ArgumentNullException(nameof(fallback));
    }

    public string Id { get; }

    public string Question { get; }

    public string Method { get; }

    /// <summary>True for a probe that gates the write code of Phases 3 to 6 (or the gate of
    /// Phase 8, for PROBE-8) until it reads <c>verified</c>.</summary>
    public bool Blocking { get; }

    /// <summary>
    /// What a refuted or unresolved answer costs: a re-plan for a blocking probe, an
    /// optimisation lost for a non-blocking one. Named here so every row the ledger writes -
    /// blocking or not - carries it, rather than the fallback living only in a comment a
    /// ledger reader cannot see (research.md R10).
    /// </summary>
    public string Fallback { get; }
}

/// <summary>
/// The fifteen stage-1 probes research.md R10 runs on the throwaway part, in the order
/// tasks.md's T033 to T038 group them. PROBE-9 and PROBE-11 join the "run on the throwaway
/// part" set that research.md's own prose lists incompletely (R10 names 1, 2, 3, 4, 5, 6, 7,
/// 10, 12, 13, 20, 21 and PROBE-8 by name, but T038 groups PROBE-9 and PROBE-11 with the other
/// throwaway-part, non-blocking probes, and neither reads anything the recipe does not
/// already build). PROBE-14 to PROBE-19 and PROBE-22 are excluded on purpose: PROBE-15 gates
/// 004's start rather than running inside it, PROBE-14, 16 and 17 need a real assembly or
/// drawing rather than the throwaway part, and PROBE-18, 19 and 22 are stage-2 only.
/// </summary>
public static class RemodelProbeCatalog
{
    private static readonly RemodelProbeDefinition[] DefinitionArray =
    {
        new RemodelProbeDefinition(
            "PROBE-1",
            "Does ISldWorks.CommandInProgress = true suppress the \"Cannot reorder\" message box?",
            "Deliberately request an illegal reorder with the flag set and with it clear, "
                + "watched from a watchdog thread; record whether the call returns or the STA "
                + "thread blocks.",
            blocking: true,
            fallback: "A refuted PROBE-1 means stage 1 cannot run unattended: an illegal "
                + "reorder hangs the add-in's STA thread, and Phases 5 and 8 stop until the "
                + "owner decides."),
        new RemodelProbeDefinition(
            "PROBE-2",
            "Equation units: does \"w\" = 120 in a millimetre part produce 120 mm, and what "
                + "unit does IEquationMgr.get_Value(i) return?",
            "Read get_Equation(i) and get_Value(i) for the recipe's global; record "
                + "IDimension.SystemValue (always metres) beside it. v1 reads no other "
                + "IDimension member.",
            blocking: true,
            fallback: "A wrong answer silently builds a 120-metre part that rebuilds cleanly "
                + "and passes every non-geometric check; the units sequence in the plan is "
                + "inverted and globals do not ship until it is right."),
        new RemodelProbeDefinition(
            "PROBE-3",
            "Does IModelDocExtension.ReorderFeature(f, anchor, swMoveAfter=3) move a feature "
                + "on 2024, and return false rather than corrupting the tree when asked to "
                + "move past a dependency?",
            "Attempt a legal reorder and an illegal one past a dependency; record the return "
                + "value and the tree order after each.",
            blocking: true,
            fallback: "A refuted PROBE-3 fails the whole reorganize-in-place premise; Phase "
                + "0's numbers decide what replaces it."),
        new RemodelProbeDefinition(
            "PROBE-4",
            "Do feature folders require contiguous members on 2024?",
            "Call IFeatureManager.InsertFeatureTreeFolder2(swFeatureTreeFolder_Containing=2) "
                + "against the recipe's contiguous box-and-cut selection, then against a "
                + "non-contiguous one; record what each did.",
            blocking: true,
            fallback: "A contiguity answer wrong in either direction re-plans folders.py "
                + "before any executor work is trusted."),
        new RemodelProbeDefinition(
            "PROBE-5",
            "Does ReorderFeature(f, folderName, swMoveToFolder=5) move a feature into an "
                + "existing folder? Does IFeatureManager.MoveToFolder work, or silently "
                + "no-op? Does IFeature.MakeSubFeature work?",
            "Attempt all three against the recipe's folder and record what each did.",
            blocking: false,
            fallback: "No: all three are optimisations only, and the folder plan needs none "
                + "of them."),
        new RemodelProbeDefinition(
            "PROBE-6",
            "Does IEquationMgr.Add3 work on 2024, or silently return -1 as observed on 2026?",
            "Record Add3's return value and GetCount() before and after.",
            blocking: false,
            fallback: "No: the verified equation helper handles both outcomes."),
        new RemodelProbeDefinition(
            "PROBE-7",
            "Does set_Equation(i, text) edit an equation in place from C#?",
            "Call set_Equation on the recipe's equation and re-read it with get_Equation.",
            blocking: false,
            fallback: "No: SetEquationAndConfigurationOption is the documented fallback."),
        new RemodelProbeDefinition(
            "PROBE-8",
            "Calibrate the tolerances: attained relative error on volume, surface area, "
                + "centre of mass and principal moments at swMassPropertyAccuracyLevel_Higher, "
                + "against a box and a cylinder of exactly known analytic volume.",
            "Build a box and a cylinder of exactly known analytic dimensions; measure each "
                + "with IModelDocExtension.CreateMassProperty2() at "
                + "swMassPropertyAccuracyLevel_Higher=2, with Recalculate()'s Boolean checked "
                + "before anything is read; record the attained relative error per quantity.",
            blocking: true,
            fallback: "A tolerance that has never been compared against a known answer does "
                + "not ship: the IDENTITY profile's bounds are raised to the measured floor "
                + "if 1e-9 is not attainable, before the gate ships."),
        new RemodelProbeDefinition(
            "PROBE-9",
            "GetWhatsWrong's out-array element type on 2024: feature names, or Feature "
                + "objects?",
            "Force a rebuild error on the throwaway part and inspect the type of the elements "
                + "GetWhatsWrong returns.",
            blocking: false,
            fallback: "No: GetErrorCode2 stays the primary reading either way."),
        new RemodelProbeDefinition(
            "PROBE-10",
            "Does the ___EndTag___ marker appear on 2024, and does it keep the folder's "
                + "default name after a rename?",
            "Create the recipe's folder, rename it, and inspect the feature tree names "
                + "around it for the marker.",
            blocking: false,
            fallback: "No: 003 already handles both shapes."),
        new RemodelProbeDefinition(
            "PROBE-11",
            "GetTypeName2 values on 2024 versus the 2026-calibrated rms_types.yaml (ICE "
                + "covering both cuts and some bosses; CommentsFolder / SelectionSetFolder / "
                + "InkMarkupFolder).",
            "Walk the recipe's features and record each GetTypeName2 answer against the "
                + "calibrated table.",
            blocking: false,
            fallback: "No: an unrecognised type name gives unresolved rather than a guess."),
        new RemodelProbeDefinition(
            "PROBE-12",
            "Does ICustomPropertyManager.Add3(key, 30, value, 2) tag the copy, and does Get4 "
                + "read it back on 2024?",
            "Tag the throwaway part with a custom property, save, reopen, and read it back "
                + "with Get4.",
            blocking: true,
            fallback: "A refuted PROBE-12 means the tag cannot be one of VerifyTarget's four "
                + "checks; the guard needs a different second identity signal before any "
                + "write code ships."),
        new RemodelProbeDefinition(
            "PROBE-13",
            "Does File.Copy succeed on a .SLDPRT SOLIDWORKS currently has open?",
            "Attempt File.Copy against the open throwaway part; on failure, attempt the "
                + "FileShare.ReadWrite stream fallback.",
            blocking: false,
            fallback: "No: the FileShare.ReadWrite stream fallback runs when File.Copy fails."),
        new RemodelProbeDefinition(
            "PROBE-20",
            "Does IFeature.Description survive a reorder and a folder wrap? Is it "
                + "per-configuration?",
            "Set a feature's description, reorder it and wrap it in the recipe's folder, "
                + "then re-read Description.",
            blocking: false,
            fallback: "No."),
        new RemodelProbeDefinition(
            "PROBE-21",
            "IEquationMgr on a part with no equations: count 0, or a throw?",
            "Call GetCount() before the recipe's equation step is added.",
            blocking: false,
            fallback: "No."),
    };

    /// <summary>Every stage-1 probe id, in the order above.</summary>
    public static readonly IReadOnlyList<string> AllIds =
        DefinitionArray.Select(definition => definition.Id).ToList();

    private static readonly IReadOnlyDictionary<string, RemodelProbeDefinition> ById =
        DefinitionArray.ToDictionary(definition => definition.Id, StringComparer.Ordinal);

    /// <summary>True when <paramref name="id"/> is one of <see cref="AllIds"/>.</summary>
    public static bool IsKnown(string? id) =>
        !string.IsNullOrWhiteSpace(id) && ById.ContainsKey(id!.Trim());

    /// <summary>The definition for <paramref name="id"/>. Throws for an unknown id.</summary>
    public static RemodelProbeDefinition Get(string id)
    {
        if (string.IsNullOrWhiteSpace(id) || !ById.TryGetValue(id.Trim(), out RemodelProbeDefinition? definition))
        {
            throw new ArgumentException($"'{id}' is not a known remodel probe id.", nameof(id));
        }

        return definition;
    }
}

/// <summary>
/// One row of the capabilities ledger (tasks.md T031): <c>{probe_id, question, method,
/// raw_result, verdict, sw_version}</c> plus the blocking flag and fallback text every row
/// carries so a blocking probe's consequence is named in the record and not only in a
/// comment, and the duration and interop members <see cref="RemodelProbeRunner"/> measured.
/// </summary>
public sealed class RemodelProbeRecord
{
    public RemodelProbeRecord(
        string probeId,
        string question,
        string method,
        bool blocking,
        string fallback,
        RemodelProbeVerdict verdict,
        IReadOnlyDictionary<string, string> rawResult,
        string swVersion,
        long durationMs,
        IReadOnlyList<string> interopMembers)
    {
        ProbeId = probeId ?? throw new ArgumentNullException(nameof(probeId));
        Question = question ?? throw new ArgumentNullException(nameof(question));
        Method = method ?? throw new ArgumentNullException(nameof(method));
        Blocking = blocking;
        Fallback = fallback ?? throw new ArgumentNullException(nameof(fallback));
        Verdict = verdict;
        RawResult = rawResult ?? new Dictionary<string, string>(StringComparer.Ordinal);
        SwVersion = swVersion ?? string.Empty;
        DurationMs = durationMs;
        InteropMembers = interopMembers ?? Array.Empty<string>();
    }

    public string ProbeId { get; }

    public string Question { get; }

    public string Method { get; }

    public bool Blocking { get; }

    public string Fallback { get; }

    public RemodelProbeVerdict Verdict { get; }

    public IReadOnlyDictionary<string, string> RawResult { get; }

    public string SwVersion { get; }

    public long DurationMs { get; }

    public IReadOnlyList<string> InteropMembers { get; }
}

/// <summary>
/// The throwaway part <see cref="IRemodelProbeHost.BuildPart"/> returns: the opaque document
/// handle, the path it was saved to, and the live feature handle for every recipe step, keyed
/// by the step's <see cref="RemodelProbeFeatureStep.Name"/> exactly as the recipe named it -
/// so a probe body (tasks.md T033 to T039) can find "the fillet" without knowing how it was
/// built. The duplicate-named fillet and chamfer are both reachable, by construction, only
/// through <see cref="RemodelProbePartRecipe.Steps"/> order, not by this dictionary's key -
/// two steps sharing a name collide in a name-keyed lookup exactly as they would in
/// SOLIDWORKS, which is the point of building the recipe that way.
///
/// Features cross this seam as <c>object</c>, exactly as <c>LiveFeature.Handle</c> and
/// <c>IRemodelDocument</c> already do: an interop type in this signature would put SOLIDWORKS
/// in the test project.
/// </summary>
public sealed class RemodelProbePart
{
    public RemodelProbePart(object document, string path, IReadOnlyList<object> features)
    {
        Document = document ?? throw new ArgumentNullException(nameof(document));
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("A save path is required.", nameof(path));
        }

        Path = path;
        Features = features ?? throw new ArgumentNullException(nameof(features));
    }

    /// <summary>The live document, opaque here.</summary>
    public object Document { get; }

    /// <summary>Where the part was saved (<see cref="RemodelProbe.AssertPartSavePath"/> already checked it).</summary>
    public string Path { get; }

    /// <summary>Every feature the recipe built, live, in the recipe's own order.</summary>
    public IReadOnlyList<object> Features { get; }
}

/// <summary>
/// What <c>probe remodel</c> needs from SOLIDWORKS: whether a document is already open, the
/// version, and building and closing the throwaway part. <see cref="SwRemodelProbeHost"/> is
/// the one real implementation; a fake stands in for every decision this command makes, so
/// those decisions - the already-open refusal, the save-path check, the ledger it writes -
/// are testable without a seat (tasks.md T031).
/// </summary>
public interface IRemodelProbeHost
{
    /// <summary><c>ISldWorks.GetFirstDocument()</c> returning non-null.</summary>
    bool AnyDocumentOpen();

    /// <summary><c>ISldWorks.RevisionNumber()</c>.</summary>
    string SwVersion();

    /// <summary>
    /// Builds <paramref name="recipe"/> as a brand-new part and saves it at
    /// <paramref name="savePath"/>, which <see cref="RemodelProbe.AssertPartSavePath"/> has
    /// already checked is inside the run folder.
    /// </summary>
    RemodelProbePart BuildPart(RemodelProbePartRecipe recipe, string savePath);

    /// <summary>Closes <paramref name="part"/>'s document. The file on disk is untouched; the caller deletes it.</summary>
    void ClosePart(RemodelProbePart part);
}

/// <summary>
/// What one probe's execution answered: a verdict it is confident enough to report as
/// <see cref="RemodelProbeVerdict.Verified"/> or <see cref="RemodelProbeVerdict.Refuted"/> (or
/// <see cref="RemodelProbeVerdict.Unresolved"/> for a probe whose own reading is genuinely
/// ambiguous, research.md's PROBE-11), the raw readings behind it, and the interop members it
/// touched to get them.
/// </summary>
public sealed class RemodelProbeReading
{
    public RemodelProbeReading(
        RemodelProbeVerdict verdict,
        IReadOnlyDictionary<string, string>? rawResult = null,
        IReadOnlyList<string>? interopMembers = null)
    {
        Verdict = verdict;
        RawResult = rawResult ?? new Dictionary<string, string>(StringComparer.Ordinal);
        InteropMembers = interopMembers ?? Array.Empty<string>();
    }

    public RemodelProbeVerdict Verdict { get; }

    public IReadOnlyDictionary<string, string> RawResult { get; }

    public IReadOnlyList<string> InteropMembers { get; }
}

/// <summary>
/// What a probe's <c>Execute</c> body is handed: the built throwaway part, the gate it must
/// route every interop call through, and the SOLIDWORKS version the ledger records beside
/// every row. Plain data - no per-probe logic - so a future probe body (tasks.md T033 to
/// T039) needs nothing else to reach the part <see cref="RemodelProbe"/> already built.
/// </summary>
public sealed class RemodelProbeContext
{
    public RemodelProbeContext(RemodelProbePart part, SwGate gate, string swVersion)
    {
        Part = part ?? throw new ArgumentNullException(nameof(part));
        Gate = gate ?? throw new ArgumentNullException(nameof(gate));
        SwVersion = swVersion ?? string.Empty;
    }

    /// <summary>The throwaway part every probe in this run measures.</summary>
    public RemodelProbePart Part { get; }

    /// <summary>The gate every probe's interop call must go through (<see cref="Guard.RemodelProbeGuard"/>).</summary>
    public SwGate Gate { get; }

    /// <summary><c>ISldWorks.RevisionNumber()</c>, read once per run.</summary>
    public string SwVersion { get; }
}

/// <summary>
/// One probe's body: reads whatever it needs from <paramref name="context"/> and answers with
/// a <see cref="RemodelProbeReading"/>. <see cref="RemodelProbeRunner"/> is what turns a throw
/// into <see cref="RemodelProbeVerdict.Unresolved"/> - a probe body never needs to catch its
/// own exceptions to get that right.
/// </summary>
public delegate RemodelProbeReading RemodelProbeExecutor(RemodelProbeContext context);

/// <summary>
/// The probe bodies tasks.md T033 to T039 add, by id. Empty here: those tasks are outside
/// T031/T032's scope, and a selected id with no entry is not a usage error - it is a real
/// probe from the research backlog that this build has not implemented yet - so
/// <see cref="RemodelProbeRunner"/> records it <c>unresolved</c> with a raw result that says
/// so, exactly as it would a probe body that threw.
/// </summary>
public static class RemodelProbeExecutors
{
    public static readonly IReadOnlyDictionary<string, RemodelProbeExecutor> ByProbeId =
        new Dictionary<string, RemodelProbeExecutor>(StringComparer.Ordinal);
}

/// <summary>
/// Runs the selected probes against a built <see cref="RemodelProbeContext"/> and turns each
/// one into a <see cref="RemodelProbeRecord"/> (tasks.md T031, T032).
///
/// The one rule this class exists to enforce: <b>a probe that throws records unresolved and
/// never verified.</b> That is true whether the probe has no registered body yet or its body
/// raised - both reach the same <c>catch</c>, because "we could not tell" is the honest answer
/// to both, and the ledger must never claim <c>verified</c> for a question nothing actually
/// answered.
/// </summary>
public static class RemodelProbeRunner
{
    /// <summary>The note a not-yet-implemented probe's row carries in <c>raw_result</c>.</summary>
    public const string NotImplementedNote =
        "not yet implemented in this build; see tasks.md Phase 2 (T033 to T039)";

    /// <summary>The <c>raw_result</c> key <see cref="NotImplementedNote"/> is filed under.</summary>
    public const string NoteKey = "note";

    /// <summary>The <c>raw_result</c> key a thrown probe body's message is filed under.</summary>
    public const string ErrorKey = "error";

    /// <summary>
    /// Runs one probe. <paramref name="executors"/> defaults to
    /// <see cref="RemodelProbeExecutors.ByProbeId"/>; a caller passes its own map only to test
    /// this method's own rules (a body that throws, a body that answers) without depending on
    /// which bodies this build ships.
    /// </summary>
    public static RemodelProbeRecord Run(
        string probeId,
        RemodelProbeContext context,
        IReadOnlyDictionary<string, RemodelProbeExecutor>? executors = null,
        Func<long>? elapsedMsFor = null)
    {
        if (context == null)
        {
            throw new ArgumentNullException(nameof(context));
        }

        RemodelProbeDefinition definition = RemodelProbeCatalog.Get(probeId);
        IReadOnlyDictionary<string, RemodelProbeExecutor> bodies = executors ?? RemodelProbeExecutors.ByProbeId;

        var stopwatch = Stopwatch.StartNew();
        RemodelProbeReading reading;

        if (!bodies.TryGetValue(definition.Id, out RemodelProbeExecutor? executor))
        {
            reading = new RemodelProbeReading(
                RemodelProbeVerdict.Unresolved,
                new Dictionary<string, string>(StringComparer.Ordinal) { [NoteKey] = NotImplementedNote });
        }
        else
        {
            try
            {
                reading = executor(context);
            }
            catch (Exception error)
            {
                reading = new RemodelProbeReading(
                    RemodelProbeVerdict.Unresolved,
                    new Dictionary<string, string>(StringComparer.Ordinal) { [ErrorKey] = error.Message });
            }
        }

        stopwatch.Stop();
        long durationMs = elapsedMsFor != null ? elapsedMsFor() : stopwatch.ElapsedMilliseconds;

        return new RemodelProbeRecord(
            definition.Id,
            definition.Question,
            definition.Method,
            definition.Blocking,
            definition.Fallback,
            reading.Verdict,
            reading.RawResult,
            context.SwVersion,
            durationMs,
            reading.InteropMembers);
    }

    /// <summary>Runs every id in <paramref name="probeIds"/>, in order.</summary>
    public static IReadOnlyList<RemodelProbeRecord> RunAll(
        IReadOnlyList<string> probeIds,
        RemodelProbeContext context,
        IReadOnlyDictionary<string, RemodelProbeExecutor>? executors = null)
    {
        if (probeIds == null)
        {
            throw new ArgumentNullException(nameof(probeIds));
        }

        return probeIds.Select(id => Run(id, context, executors)).ToList();
    }
}

/// <summary>
/// What <c>probe remodel</c> was asked to do (tasks.md T031, contracts/run-artifacts.md's
/// capabilities ledger).
/// </summary>
public sealed class RemodelProbeSettings
{
    /// <summary>Where <c>capabilities/remodel-&lt;sw-version&gt;.yaml</c> and the throwaway part's own subfolder go.</summary>
    public string OutputDirectory { get; set; } = string.Empty;

    /// <summary>The probes to run; <see cref="RemodelProbeCatalog.AllIds"/> when <c>--probe</c> was not given.</summary>
    public IReadOnlyList<string> ProbeIds { get; set; } = RemodelProbeCatalog.AllIds;

    /// <summary><c>--keep-part</c>: the throwaway part's file survives the run.</summary>
    public bool KeepPart { get; set; }

    /// <summary><c>--acknowledge-throwaway-part</c>. False refuses the run.</summary>
    public bool Acknowledged { get; set; }
}

/// <summary>
/// The pure logic of <c>probe remodel</c> (tasks.md T031, T032): the refusal messages, the
/// throwaway part's save-path safety check, the log lines, and
/// <see cref="RemodelProbeLedger"/>'s YAML rendering. Everything that talks to SOLIDWORKS is
/// <see cref="SwRemodelProbeHost"/>, which this class knows nothing about.
/// </summary>
public static class RemodelProbe
{
    /// <summary>
    /// The refusal for a missing <c>--acknowledge-throwaway-part</c>, said in one place
    /// (the <c>suppress-test</c> precedent, contracts/cli.md row 20).
    /// </summary>
    public const string AcknowledgementRequiredMessage =
        "probe remodel builds a throwaway part in the run folder to measure SOLIDWORKS "
        + "against. Re-run it with --acknowledge-throwaway-part once you are willing to have "
        + "one built (it never touches a document you have open, and it is deleted afterwards "
        + "unless you pass --keep-part).";

    /// <summary>
    /// The refusal for a SOLIDWORKS session that already has a document open: the probe never
    /// touches an engineer's file, and the simplest way to be sure of that is to refuse
    /// outright rather than assume the open document is unrelated (research.md Phase 2).
    /// </summary>
    public const string DocumentAlreadyOpenMessage =
        "SOLIDWORKS already has a document open. probe remodel refuses to run while one is: "
        + "it builds and measures a throwaway part of its own, and the surest way to guarantee "
        + "it never reaches your file is to require that nothing is open when it starts. Close "
        + "your document (or run this from a session with none open) and try again.";

    /// <summary>The extension the throwaway part's save path must carry.</summary>
    public const string PartExtension = ".SLDPRT";

    /// <summary>
    /// The one safety check on where the throwaway part is written: inside
    /// <paramref name="runFolder"/>, spelled <see cref="PartExtension"/>. There is no
    /// engineer's source to protect here - unlike <c>RemodelScope.AssertSaveTarget</c>, which
    /// exists because the stage-1 executor's copy sits beside a source it must never
    /// overwrite - so this check is the narrower one a brand-new document actually needs.
    /// </summary>
    public static void AssertPartSavePath(string savePath, string runFolder)
    {
        if (string.IsNullOrWhiteSpace(savePath))
        {
            throw new ArgumentException("A save path is required.", nameof(savePath));
        }

        if (string.IsNullOrWhiteSpace(runFolder))
        {
            throw new ArgumentException("A run folder is required.", nameof(runFolder));
        }

        if (!string.Equals(Path.GetExtension(savePath), PartExtension, StringComparison.OrdinalIgnoreCase))
        {
            throw new RemodelProbeRefusedError(
                $"'{savePath}' does not end in {PartExtension}; the throwaway part is always "
                + "saved with that extension.");
        }

        string fullSavePath = Path.GetFullPath(savePath);
        string fullRunFolder = Path.GetFullPath(runFolder);
        string runFolderWithSeparator = fullRunFolder.TrimEnd(
            Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;

        if (!fullSavePath.StartsWith(runFolderWithSeparator, StringComparison.OrdinalIgnoreCase))
        {
            throw new RemodelProbeRefusedError(
                $"'{savePath}' resolves to '{fullSavePath}', which is outside the run folder "
                + $"'{fullRunFolder}'. The throwaway part is only ever written inside the run "
                + "folder it was asked to build in.");
        }
    }

    /// <summary>
    /// The lines the command writes to its log and stderr (the <c>suppress-test.log</c>
    /// precedent): how many probes settled which way, the distinct interop members the gate
    /// saw, the ledger path, and - named explicitly, so a blocking refusal cannot be missed in
    /// a long run - every blocking probe that did not read <c>verified</c>, with its fallback.
    /// </summary>
    public static IReadOnlyList<string> LogLines(
        IReadOnlyList<RemodelProbeRecord> records, IReadOnlyList<string> gatedMembers, string ledgerPath)
    {
        if (records == null)
        {
            throw new ArgumentNullException(nameof(records));
        }

        var lines = new List<string>
        {
            $"probes: {records.Count} run "
                + $"({Count(records, RemodelProbeVerdict.Verified)} verified, "
                + $"{Count(records, RemodelProbeVerdict.Refuted)} refuted, "
                + $"{Count(records, RemodelProbeVerdict.Unresolved)} unresolved)",
            "interop members: "
                + (gatedMembers == null || gatedMembers.Count == 0
                    ? "(none)"
                    : string.Join(", ", gatedMembers)),
            $"Wrote {ledgerPath}",
        };

        foreach (RemodelProbeRecord record in records)
        {
            if (record.Blocking && record.Verdict != RemodelProbeVerdict.Verified)
            {
                lines.Add(
                    $"BLOCKING {record.ProbeId} is {record.Verdict.CliName()}: {record.Fallback}");
            }
        }

        return lines;
    }

    private static int Count(IReadOnlyList<RemodelProbeRecord> records, RemodelProbeVerdict verdict) =>
        records.Count(record => record.Verdict == verdict);
}

/// <summary>
/// Writes the capabilities ledger, <c>capabilities/remodel-&lt;sw-version&gt;.yaml</c>
/// (tasks.md T032), with one row per probe in the shape T031 names:
/// <c>{probe_id, question, method, raw_result, verdict, sw_version}</c>, plus
/// <c>blocking</c>, <c>fallback</c>, <c>duration_ms</c> and <c>interop_members</c>.
///
/// Hand-written rather than pulled from a library, the same call CommandLine.cs makes for the
/// option parser: the shape is fixed and small, and every string scalar is double-quoted with
/// C-style escaping, which sidesteps YAML's block-scalar ambiguity entirely rather than
/// deciding per value whether quoting is required.
/// </summary>
public static class RemodelProbeLedger
{
    public const string DirectoryName = "capabilities";

    private const string FileNamePrefix = "remodel-";

    private const string FileNameExtension = ".yaml";

    /// <summary>
    /// <c>&lt;outputDirectory&gt;/capabilities/remodel-&lt;sw-version&gt;.yaml</c>. A SOLIDWORKS
    /// version that contains no filesystem-hostile character (research.md: "32.5.0.48" style)
    /// is used as-is; anything else is sanitised rather than left to throw deep inside
    /// <see cref="System.IO.File"/>.
    /// </summary>
    public static string FilePath(string outputDirectory, string swVersion)
    {
        if (string.IsNullOrWhiteSpace(outputDirectory))
        {
            throw new ArgumentException("An output directory is required.", nameof(outputDirectory));
        }

        return Path.Combine(
            outputDirectory,
            DirectoryName,
            FileNamePrefix + SanitizeForFileName(swVersion) + FileNameExtension);
    }

    /// <summary>The YAML text for <paramref name="records"/>. Pure: no filesystem access.</summary>
    public static string Render(
        string swVersion, IReadOnlyList<RemodelProbeRecord> records, DateTimeOffset generatedAt)
    {
        if (records == null)
        {
            throw new ArgumentNullException(nameof(records));
        }

        var text = new StringBuilder();
        text.Append("sw_version: ").Append(Quote(swVersion)).Append('\n');
        text.Append("generated_at: ")
            .Append(Quote(generatedAt.ToString("o", CultureInfo.InvariantCulture)))
            .Append('\n');

        if (records.Count == 0)
        {
            text.Append("probes: []\n");
            return text.ToString();
        }

        text.Append("probes:\n");
        foreach (RemodelProbeRecord record in records)
        {
            text.Append("  - probe_id: ").Append(Quote(record.ProbeId)).Append('\n');
            text.Append("    question: ").Append(Quote(record.Question)).Append('\n');
            text.Append("    method: ").Append(Quote(record.Method)).Append('\n');
            text.Append("    blocking: ").Append(record.Blocking ? "true" : "false").Append('\n');
            text.Append("    fallback: ").Append(Quote(record.Fallback)).Append('\n');
            text.Append("    verdict: ").Append(record.Verdict.CliName()).Append('\n');
            text.Append("    sw_version: ").Append(Quote(record.SwVersion)).Append('\n');
            text.Append("    duration_ms: ")
                .Append(record.DurationMs.ToString(CultureInfo.InvariantCulture))
                .Append('\n');
            AppendStringList(text, "    interop_members", record.InteropMembers);
            AppendStringMap(text, "    raw_result", record.RawResult);
        }

        return text.ToString();
    }

    /// <summary>Renders and writes the ledger, creating <c>capabilities/</c> if needed. Returns the path written.</summary>
    public static string Write(
        string outputDirectory,
        string swVersion,
        IReadOnlyList<RemodelProbeRecord> records,
        DateTimeOffset? generatedAt = null)
    {
        string path = FilePath(outputDirectory, swVersion);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, Render(swVersion, records, generatedAt ?? DateTimeOffset.UtcNow), Encoding.UTF8);
        return path;
    }

    private static void AppendStringList(StringBuilder text, string key, IReadOnlyList<string> items)
    {
        if (items.Count == 0)
        {
            text.Append(key).Append(": []\n");
            return;
        }

        text.Append(key).Append(":\n");
        foreach (string item in items)
        {
            text.Append("      - ").Append(Quote(item)).Append('\n');
        }
    }

    private static void AppendStringMap(StringBuilder text, string key, IReadOnlyDictionary<string, string> map)
    {
        if (map.Count == 0)
        {
            text.Append(key).Append(": {}\n");
            return;
        }

        text.Append(key).Append(":\n");
        foreach (KeyValuePair<string, string> entry in map)
        {
            text.Append("      ").Append(Quote(entry.Key)).Append(": ").Append(Quote(entry.Value)).Append('\n');
        }
    }

    private static string Quote(string? value)
    {
        var quoted = new StringBuilder();
        quoted.Append('"');
        foreach (char c in value ?? string.Empty)
        {
            switch (c)
            {
                case '"':
                    quoted.Append("\\\"");
                    break;
                case '\\':
                    quoted.Append("\\\\");
                    break;
                case '\n':
                    quoted.Append("\\n");
                    break;
                case '\r':
                    quoted.Append("\\r");
                    break;
                case '\t':
                    quoted.Append("\\t");
                    break;
                default:
                    quoted.Append(c);
                    break;
            }
        }

        quoted.Append('"');
        return quoted.ToString();
    }

    private static string SanitizeForFileName(string? swVersion)
    {
        if (string.IsNullOrWhiteSpace(swVersion))
        {
            return "unknown";
        }

        var safe = new StringBuilder(swVersion!.Length);
        foreach (char c in swVersion)
        {
            safe.Append(Array.IndexOf(Path.GetInvalidFileNameChars(), c) >= 0 ? '_' : c);
        }

        return safe.ToString();
    }
}
