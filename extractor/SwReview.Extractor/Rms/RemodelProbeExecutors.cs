using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using SolidWorks.Interop.swconst;

namespace SwReview.Extractor.Rms;

/// <summary>
/// PROBE-1's decision, pure and independent of how the two attempts were actually run
/// (<see cref="RemodelProbeWatchdog"/>): whether an illegal reorder blocked with
/// <c>CommandInProgress</c> clear, and again with it set.
/// </summary>
public static class RemodelProbe1Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(bool blockedWithFlagClear, bool blockedWithFlagSet)
    {
        if (!blockedWithFlagClear && !blockedWithFlagSet)
        {
            return (
                RemodelProbeVerdict.Unresolved,
                "the illegal reorder never raised a message box even with CommandInProgress clear, "
                    + "so whether the flag would have suppressed one is untested.");
        }

        if (blockedWithFlagClear && !blockedWithFlagSet)
        {
            return (
                RemodelProbeVerdict.Verified,
                "the illegal reorder blocked with CommandInProgress clear and returned once it was "
                    + "set: the flag suppresses the message box.");
        }

        if (blockedWithFlagClear && blockedWithFlagSet)
        {
            return (
                RemodelProbeVerdict.Refuted,
                "the illegal reorder blocked with CommandInProgress set to true as well: the flag "
                    + "does not suppress the message box, and stage 1 cannot run unattended until "
                    + "the owner decides what replaces it.");
        }

        return (
            RemodelProbeVerdict.Unresolved,
            "the illegal reorder blocked only with the flag set, the opposite of what setting it "
                + "should do; this result needs a human look before it is trusted either way.");
    }
}

/// <summary>PROBE-3's decision: does <c>ReorderFeature</c> move a feature, and refuse cleanly past a dependency?</summary>
public static class RemodelProbe3Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(
        bool legalReturned, bool legalOrderUnchanged, bool illegalReturned, bool illegalOrderUnchanged)
    {
        if (!illegalOrderUnchanged)
        {
            return (
                RemodelProbeVerdict.Refuted,
                "the illegal reorder past a dependency changed the tree order: ReorderFeature "
                    + "corrupted the tree instead of refusing.");
        }

        if (illegalReturned)
        {
            return (
                RemodelProbeVerdict.Refuted,
                "the illegal reorder past a dependency returned true instead of a bare false.");
        }

        if (!legalOrderUnchanged)
        {
            return (
                RemodelProbeVerdict.Unresolved,
                "the benign reorder changed the tree order unexpectedly; this needs a human look "
                    + "before either verdict is trusted.");
        }

        if (!legalReturned)
        {
            return (
                RemodelProbeVerdict.Refuted,
                "ReorderFeature returned false even for a feature already in the requested "
                    + "position: it cannot be trusted to report success on a benign request.");
        }

        return (
            RemodelProbeVerdict.Verified,
            "the benign reorder returned true and left the tree unchanged; the illegal one "
                + "returned false and left the tree unchanged too.");
    }
}

/// <summary>PROBE-4's decision: do folders require contiguous members on 2024?</summary>
public static class RemodelProbe4Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(bool contiguousFolderBuilt, bool nonContiguousFolderBuilt)
    {
        if (contiguousFolderBuilt && !nonContiguousFolderBuilt)
        {
            return (
                RemodelProbeVerdict.Verified,
                "contiguous members produced a folder and non-contiguous members did not: folders "
                    + "require contiguity on 2024, matching the 2026 assumption.");
        }

        if (!contiguousFolderBuilt)
        {
            return (
                RemodelProbeVerdict.Refuted,
                "the recipe's own contiguous box-and-cut selection did not produce a folder; the "
                    + "whole folder plan needs re-checking before it is trusted.");
        }

        return (
            RemodelProbeVerdict.Refuted,
            "a non-contiguous selection produced a folder anyway: 2024 does not require "
                + "contiguity, contradicting the 2026-based assumption folders.py is built on.");
    }
}

/// <summary>PROBE-6's decision: does <c>Add3</c> work, or silently return -1 and add nothing?</summary>
public static class RemodelProbe6Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(int countBefore, int addResult, int countAfter)
    {
        bool countIncreased = countAfter == countBefore + 1;

        if (addResult != -1 && countIncreased)
        {
            return (RemodelProbeVerdict.Verified, "Add3 returned a real index and the count increased by one: it works on 2024.");
        }

        if (addResult == -1 && !countIncreased)
        {
            return (RemodelProbeVerdict.Refuted, "Add3 returned -1 and added nothing, matching the 2026 bug.");
        }

        return (
            RemodelProbeVerdict.Unresolved,
            $"Add3 returned {addResult.ToString(CultureInfo.InvariantCulture)} and the count went "
                + $"from {countBefore.ToString(CultureInfo.InvariantCulture)} to "
                + $"{countAfter.ToString(CultureInfo.InvariantCulture)}, a combination that matches "
                + "neither the working nor the known-broken pattern.");
    }
}

/// <summary>PROBE-9's decision: what element kind did <c>GetWhatsWrong</c>'s <c>Features</c> array hold?</summary>
public static class RemodelProbe9Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(bool suppressReturned, RemodelWhatsWrongReading whatsWrong)
    {
        if (whatsWrong == null)
        {
            throw new ArgumentNullException(nameof(whatsWrong));
        }

        if (!suppressReturned)
        {
            return (RemodelProbeVerdict.Unresolved, "SetSuppression2 returned false, so no rebuild error could be forced to inspect.");
        }

        if (whatsWrong.Count == 0)
        {
            return (
                RemodelProbeVerdict.Unresolved,
                "suppressing the box did not raise any rebuild error to inspect - GetErrorCode2 "
                    + "remains the primary reading either way.");
        }

        if (whatsWrong.ElementKind == "feature_names" || whatsWrong.ElementKind == "feature_objects")
        {
            return (RemodelProbeVerdict.Verified, $"GetWhatsWrong's Features array held {whatsWrong.ElementKind} on this build.");
        }

        return (
            RemodelProbeVerdict.Unresolved,
            $"GetWhatsWrong's Features array held an unrecognised element kind "
                + $"({whatsWrong.ElementKind}); this gives unresolved rather than a guess.");
    }
}

/// <summary>PROBE-10's decision: does the ___EndTag___ marker appear, and does it keep the folder's default name?</summary>
public static class RemodelProbe10Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(
        bool markerBefore, string? markerNameAfter, string defaultFolderName, string newFolderName)
    {
        if (!markerBefore && markerNameAfter == null)
        {
            return (RemodelProbeVerdict.Verified, "no ___EndTag___ marker appeared on 2024, before or after the rename.");
        }

        if (markerNameAfter == null)
        {
            return (
                RemodelProbeVerdict.Unresolved,
                "the marker was present before the rename but is no longer findable after it; "
                    + "this needs a human look.");
        }

        if (markerNameAfter.Contains(defaultFolderName) && !markerNameAfter.Contains(newFolderName))
        {
            return (RemodelProbeVerdict.Verified, "the marker is present and still names the folder's default name after the rename.");
        }

        if (markerNameAfter.Contains(newFolderName))
        {
            return (RemodelProbeVerdict.Refuted, "the marker tracked the rename instead of keeping the folder's default name.");
        }

        return (
            RemodelProbeVerdict.Unresolved,
            $"a marker-like name ('{markerNameAfter}') was found but names neither the default "
                + "nor the renamed folder.");
    }
}

/// <summary>PROBE-12's decision: did the tag survive a save, close and reopen?</summary>
public static class RemodelProbe12Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(
        bool saved, bool foundAfterReopen, string? valueAfterReopen, string expectedValue)
    {
        if (!saved)
        {
            return (
                RemodelProbeVerdict.Unresolved,
                "the tagged part could not be saved, so the close-and-reopen round trip was never genuinely tested.");
        }

        if (foundAfterReopen && string.Equals(valueAfterReopen, expectedValue, StringComparison.Ordinal))
        {
            return (RemodelProbeVerdict.Verified, "Add3 tagged the document and Get4 read the same value back after a save, close and reopen.");
        }

        if (!foundAfterReopen)
        {
            return (RemodelProbeVerdict.Refuted, "Get4 could not find the tag after the document was reopened.");
        }

        return (
            RemodelProbeVerdict.Refuted,
            $"the tag was found after reopening but reads '{valueAfterReopen}' instead of the value written.");
    }
}

/// <summary>
/// PROBE-13's decision. Only <see cref="Decide"/> is unit-tested against known booleans:
/// whether a real Windows file lock lets <c>File.Copy</c> fail while a
/// <c>FileShare.ReadWrite</c>-mode <c>FileStream</c> open of the very same source succeeds is a
/// property of whatever lock SOLIDWORKS actually takes (research RK-9), which only the
/// workstation run can produce - a portable unit test cannot manufacture that specific
/// combination without a real SOLIDWORKS session holding the file.
/// </summary>
public static class RemodelProbe13Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(bool copySucceeded, bool fallbackSucceeded)
    {
        if (copySucceeded)
        {
            return (RemodelProbeVerdict.Verified, "File.Copy succeeded against the open .SLDPRT directly.");
        }

        if (fallbackSucceeded)
        {
            return (
                RemodelProbeVerdict.Refuted,
                "File.Copy failed against the open .SLDPRT, but the FileShare.ReadWrite stream fallback succeeded.");
        }

        return (
            RemodelProbeVerdict.Unresolved,
            "neither File.Copy nor the FileShare.ReadWrite stream fallback could copy the open .SLDPRT.");
    }
}

/// <summary>PROBE-20's decision: did the description survive being moved into a folder?</summary>
public static class RemodelProbe20Logic
{
    public static (RemodelProbeVerdict Verdict, string Reason) Decide(
        bool movedIntoFolder, string expectedDescription, string? descriptionAfter)
    {
        if (!movedIntoFolder)
        {
            return (
                RemodelProbeVerdict.Unresolved,
                "the reorder into the folder did not succeed, so description survival across it was not genuinely tested.");
        }

        if (string.Equals(descriptionAfter, expectedDescription, StringComparison.Ordinal))
        {
            return (RemodelProbeVerdict.Verified, "the description survived being moved into a folder.");
        }

        return (RemodelProbeVerdict.Refuted, $"the description read back as '{descriptionAfter}' instead of what was set.");
    }
}

/// <summary>
/// The fifteen probe bodies (tasks.md T033 to T039), registered against
/// <see cref="RemodelProbeCatalog"/>'s ids. Every body reaches SOLIDWORKS only through
/// <see cref="RemodelProbeContext.Host"/>; the decision each one reaches is a pure function
/// above, factored out so it is testable without scripting a fake host at all.
/// </summary>
public static partial class RemodelProbeExecutors
{
    public static readonly IReadOnlyDictionary<string, RemodelProbeExecutor> ByProbeId =
        new Dictionary<string, RemodelProbeExecutor>(StringComparer.Ordinal)
        {
            ["PROBE-1"] = Probe1,
            ["PROBE-2"] = Probe2,
            ["PROBE-3"] = Probe3,
            ["PROBE-4"] = Probe4,
            ["PROBE-5"] = Probe5,
            ["PROBE-6"] = Probe6,
            ["PROBE-7"] = Probe7,
            ["PROBE-8"] = Probe8,
            ["PROBE-9"] = Probe9,
            ["PROBE-10"] = Probe10,
            ["PROBE-11"] = Probe11,
            ["PROBE-12"] = Probe12,
            ["PROBE-13"] = Probe13,
            ["PROBE-20"] = Probe20,
            ["PROBE-21"] = Probe21,
        };

    /// <summary>
    /// The recipe's own folder step index, computed once from <see cref="RemodelProbePartRecipe.Default"/>
    /// rather than hard-coded, so PROBE-4 cannot silently drift from the recipe it reads.
    /// </summary>
    private static readonly int FolderStepIndex = RemodelProbePartRecipe.Default().Steps
        .Select((step, index) => (step, index))
        .Single(pair => pair.step.Kind == RemodelProbeFeatureKind.Folder)
        .index;

    private static readonly AnalyticSolidSpec Probe8Box = AnalyticSolidSpec.Box(0.08, 0.05, 0.03);

    private static readonly AnalyticSolidSpec Probe8Cylinder = AnalyticSolidSpec.Cylinder(0.02, 0.06);

    // ---- PROBE-1: the watchdog-timed illegal reorder, flag clear and flag set ----------

    private static RemodelProbeReading Probe1(RemodelProbeContext context)
    {
        const string mover = "Boss-Extrude1";
        const string anchor = "Shell1";
        int illegalLocation = (int)swMoveLocation_e.swMoveAfter;

        context.Gate.Call(RemodelSystemToggles.CommandInProgressMember, () => context.Host.SetCommandInProgress(false));
        RemodelProbeWatchdogOutcome clearOutcome = RemodelProbeWatchdog.RunWithTimeout(
            () => context.Host.ReorderFeature(context.Part, mover, anchor, illegalLocation), context.WatchdogTimeout);

        context.Gate.Call(RemodelSystemToggles.CommandInProgressMember, () => context.Host.SetCommandInProgress(true));
        RemodelProbeWatchdogOutcome setOutcome = RemodelProbeWatchdog.RunWithTimeout(
            () => context.Host.ReorderFeature(context.Part, mover, anchor, illegalLocation), context.WatchdogTimeout);

        bool blockedClear = !clearOutcome.Completed;
        bool blockedSet = !setOutcome.Completed;
        (RemodelProbeVerdict verdict, string reason) = RemodelProbe1Logic.Decide(blockedClear, blockedSet);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["blocked_with_flag_clear"] = blockedClear.ToString(),
            ["blocked_with_flag_set"] = blockedSet.ToString(),
            ["returned_with_flag_clear"] = clearOutcome.Completed ? clearOutcome.Result.ToString() : "n/a (blocked)",
            ["returned_with_flag_set"] = setOutcome.Completed ? setOutcome.Result.ToString() : "n/a (blocked)",
            ["reason"] = reason,
        };

        return new RemodelProbeReading(
            verdict,
            raw,
            new[] { SwRemodelProbeHost.Member.ReorderFeature, RemodelSystemToggles.CommandInProgressMember });
    }

    // ---- PROBE-2: equation units -------------------------------------------------------

    private static RemodelProbeReading Probe2(RemodelProbeContext context)
    {
        IEquationTarget equations = context.Host.GetEquationManager(context.Part);
        int count = equations.GetCount();

        int index = -1;
        string? text = null;
        for (int i = 0; i < count; i++)
        {
            string? candidate = equations.GetEquation(i);
            if (candidate != null && candidate.Contains("\"w\""))
            {
                index = i;
                text = candidate;
                break;
            }
        }

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["equation_count"] = count.ToString(CultureInfo.InvariantCulture),
        };

        var interopMembers = new[]
        {
            SwRemodelProbeHost.Member.EquationGetCount,
            SwRemodelProbeHost.Member.EquationGetEquationText,
            SwRemodelProbeHost.Member.EquationGetValue,
        };

        if (index < 0)
        {
            raw["reason"] = "the recipe's \"w\" = 120 global equation was not found among the part's equations.";
            return new RemodelProbeReading(RemodelProbeVerdict.Unresolved, raw, interopMembers);
        }

        double value = context.Host.GetEquationValue(context.Part, index);
        raw["equation_text"] = text ?? string.Empty;
        raw["equation_value"] = value.ToString("R", CultureInfo.InvariantCulture);

        const double DocumentUnitsExpected = 120.0;
        const double MetresExpected = 0.12;
        const double Tolerance = 1e-6;

        if (Math.Abs(value - DocumentUnitsExpected) < Tolerance)
        {
            raw["unit"] = "document_units_mm";
            raw["reason"] = "get_Value returned 120: the equation number is in the document's length unit, matching R3.6.";
            return new RemodelProbeReading(RemodelProbeVerdict.Verified, raw, interopMembers);
        }

        if (Math.Abs(value - MetresExpected) < Tolerance)
        {
            raw["unit"] = "metres";
            raw["reason"] =
                "get_Value returned 0.12 (metres): the planner's mm-to-document-unit conversion "
                + "(R3.6) is backwards and must be inverted before any global ships.";
            return new RemodelProbeReading(RemodelProbeVerdict.Refuted, raw, interopMembers);
        }

        raw["reason"] = "get_Value returned neither 120 (document units) nor 0.12 (metres).";
        return new RemodelProbeReading(RemodelProbeVerdict.Unresolved, raw, interopMembers);
    }

    // ---- PROBE-3: reorder moves a feature, and refuses cleanly past a dependency -------

    private static RemodelProbeReading Probe3(RemodelProbeContext context)
    {
        const string box = "Boss-Extrude1";
        const string cut = "Cut-Extrude1";
        const string shell = "Shell1";
        int after = (int)swMoveLocation_e.swMoveAfter;

        IReadOnlyList<string> before = context.Host.GetFeatureNames(context.Part);

        // Legal: ask to move Cut-Extrude1 to right after Boss-Extrude1 - its current position
        // already. Every adjacent pair in this five-feature chain genuinely depends on the one
        // before it, so a request that changes nothing is the only reorder this recipe can offer
        // that is not also a dependency violation; it still exercises whether the call answers
        // true and leaves a well-formed request alone.
        bool legalReturned = context.Host.ReorderFeature(context.Part, cut, box, after);
        IReadOnlyList<string> afterLegal = context.Host.GetFeatureNames(context.Part);

        // Illegal: move the box - everything else depends on it - to after the very last feature.
        bool illegalReturned = context.Host.ReorderFeature(context.Part, box, shell, after);
        IReadOnlyList<string> afterIllegal = context.Host.GetFeatureNames(context.Part);

        bool legalOrderUnchanged = afterLegal.SequenceEqual(before);
        bool illegalOrderUnchanged = afterIllegal.SequenceEqual(afterLegal);

        (RemodelProbeVerdict verdict, string reason) =
            RemodelProbe3Logic.Decide(legalReturned, legalOrderUnchanged, illegalReturned, illegalOrderUnchanged);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["legal_returned"] = legalReturned.ToString(),
            ["legal_order_unchanged"] = legalOrderUnchanged.ToString(),
            ["illegal_returned"] = illegalReturned.ToString(),
            ["illegal_order_unchanged"] = illegalOrderUnchanged.ToString(),
            ["tree_before"] = string.Join(",", before),
            ["tree_after_illegal"] = string.Join(",", afterIllegal),
            ["reason"] = reason,
        };

        return new RemodelProbeReading(
            verdict, raw, new[] { SwRemodelProbeHost.Member.ReorderFeature, SwRemodelProbeHost.Member.GetName });
    }

    // ---- PROBE-4: do folders require contiguous members? -------------------------------

    private static RemodelProbeReading Probe4(RemodelProbeContext context)
    {
        // Contiguous: the recipe's own Folder1 step already wrapped Boss-Extrude1 and
        // Cut-Extrude1; a second attempt around the same pair would introduce untested
        // nested-folder behaviour this probe does not need.
        bool contiguousFolderBuilt = context.Part.Features[FolderStepIndex] != null;

        // Non-contiguous: the fillet and the shell, with the chamfer - sharing the fillet's own
        // name, RemodelProbePartRecipe.Default's deliberate duplicate - sitting between them.
        object? nonContiguous = context.Host.TryInsertFeatureTreeFolder(context.Part, new[] { "Fillet1", "Shell1" });
        bool nonContiguousFolderBuilt = nonContiguous != null;

        (RemodelProbeVerdict verdict, string reason) = RemodelProbe4Logic.Decide(contiguousFolderBuilt, nonContiguousFolderBuilt);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["contiguous_folder_built"] = contiguousFolderBuilt.ToString(),
            ["non_contiguous_folder_built"] = nonContiguousFolderBuilt.ToString(),
            ["reason"] = reason,
        };

        return new RemodelProbeReading(
            verdict,
            raw,
            new[] { SwRemodelProbeHost.Member.InsertFeatureTreeFolder2, SwRemodelProbeHost.Member.Select2 });
    }

    // ---- PROBE-5: the three folder optimisations, each recorded independently ----------

    private static RemodelProbeReading Probe5(RemodelProbeContext context)
    {
        const string folder = "Folder1";
        const string moveTarget = "Shell1";
        const string subFeature = "Fillet1";
        int toFolder = (int)swMoveLocation_e.swMoveToFolder;

        var raw = new Dictionary<string, string>(StringComparer.Ordinal);
        int attempts = 0;
        int successes = 0;

        attempts++;
        try
        {
            bool result = context.Host.ReorderFeature(context.Part, moveTarget, folder, toFolder);
            raw["reorder_to_folder"] = result.ToString();
            successes++;
        }
        catch (Exception error)
        {
            raw["reorder_to_folder"] = "error: " + error.Message;
        }

        attempts++;
        try
        {
            bool result = context.Host.MoveToFolder(context.Part, folder, subFeature, true);
            raw["move_to_folder"] = result.ToString();
            successes++;
        }
        catch (Exception error)
        {
            raw["move_to_folder"] = "error: " + error.Message;
        }

        attempts++;
        try
        {
            bool result = context.Host.MakeSubFeature(context.Part, folder, subFeature);
            raw["make_sub_feature"] = result.ToString();
            successes++;
        }
        catch (Exception error)
        {
            raw["make_sub_feature"] = "error: " + error.Message;
        }

        RemodelProbeVerdict verdict = successes == attempts ? RemodelProbeVerdict.Verified : RemodelProbeVerdict.Unresolved;
        raw["reason"] = successes == attempts
            ? "all three optimisation calls answered without throwing; the folder plan needs none of them regardless of what they answered."
            : $"{(attempts - successes).ToString(CultureInfo.InvariantCulture)} of "
                + $"{attempts.ToString(CultureInfo.InvariantCulture)} calls threw; see the per-call entries above.";

        return new RemodelProbeReading(
            verdict,
            raw,
            new[]
            {
                SwRemodelProbeHost.Member.ReorderFeature,
                SwRemodelProbeHost.Member.MoveToFolder,
                SwRemodelProbeHost.Member.MakeSubFeature,
            });
    }

    // ---- PROBE-6: does Add3 work, or silently return -1? --------------------------------

    private static RemodelProbeReading Probe6(RemodelProbeContext context)
    {
        IEquationTarget equations = context.Host.GetEquationManager(context.Part);
        int before = equations.GetCount();
        int addResult = equations.Add3(-1, "\"probe6check\" = 42", true, (int)swInConfigurationOpts_e.swAllConfiguration, null);
        int after = equations.GetCount();

        (RemodelProbeVerdict verdict, string reason) = RemodelProbe6Logic.Decide(before, addResult, after);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["count_before"] = before.ToString(CultureInfo.InvariantCulture),
            ["add3_result"] = addResult.ToString(CultureInfo.InvariantCulture),
            ["count_after"] = after.ToString(CultureInfo.InvariantCulture),
            ["reason"] = reason,
        };

        return new RemodelProbeReading(
            verdict, raw, new[] { SwRemodelProbeHost.Member.AddEquation, SwRemodelProbeHost.Member.EquationGetCount });
    }

    // ---- PROBE-7: does set_Equation edit in place? --------------------------------------

    private static RemodelProbeReading Probe7(RemodelProbeContext context)
    {
        IEquationTarget equations = context.Host.GetEquationManager(context.Part);

        int index = equations.Add3(-1, "\"probe7check\" = 1", true, (int)swInConfigurationOpts_e.swAllConfiguration, null);
        if (index < 0)
        {
            index = equations.Add2(-1, "\"probe7check\" = 1", true);
        }

        if (index < 0)
        {
            return new RemodelProbeReading(
                RemodelProbeVerdict.Unresolved,
                new Dictionary<string, string>(StringComparer.Ordinal)
                {
                    ["reason"] = "neither Add3 nor Add2 could add a scratch equation to test set_Equation against.",
                },
                new[] { SwRemodelProbeHost.Member.AddEquation, SwRemodelProbeHost.Member.EquationAdd2 });
        }

        string? before = equations.GetEquation(index);
        equations.SetEquation(index, "\"probe7check\" = 99");
        string? after = equations.GetEquation(index);

        bool changed = after != null && after.Contains("99") && !string.Equals(after, before, StringComparison.Ordinal);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["before"] = before ?? "(null)",
            ["after"] = after ?? "(null)",
            ["reason"] = changed
                ? "set_Equation's edit is reflected on the next read."
                : "set_Equation did not change the readable text - it may be a no-op from C# too.",
        };

        return new RemodelProbeReading(
            changed ? RemodelProbeVerdict.Verified : RemodelProbeVerdict.Refuted,
            raw,
            new[]
            {
                SwRemodelProbeHost.Member.AddEquation,
                SwRemodelProbeHost.Member.EquationSetEquation,
                SwRemodelProbeHost.Member.EquationGetEquationText,
            });
    }

    // ---- PROBE-8: tolerance calibration on a box and a cylinder -------------------------

    private static RemodelProbeReading Probe8(RemodelProbeContext context)
    {
        var raw = new Dictionary<string, string>(StringComparer.Ordinal);
        bool anyMeasured = false;
        bool anyFailed = false;

        foreach ((string label, AnalyticSolidSpec spec) in new[] { ("box", Probe8Box), ("cylinder", Probe8Cylinder) })
        {
            MeasureOneAnalyticSolid(context, label, spec, raw, ref anyMeasured, ref anyFailed);
        }

        RemodelProbeVerdict verdict = anyMeasured && !anyFailed ? RemodelProbeVerdict.Verified : RemodelProbeVerdict.Unresolved;
        raw["reason"] = verdict == RemodelProbeVerdict.Verified
            ? "both shapes measured cleanly; the attained relative errors above are the calibration this probe exists to produce."
            : "at least one shape's measurement was incomplete; see the per-shape status fields.";

        return new RemodelProbeReading(
            verdict,
            raw,
            new[]
            {
                SwRemodelProbeHost.Member.CreateMassProperty2,
                SwRemodelProbeHost.Member.MassPropertySetAccuracyLevel,
                SwRemodelProbeHost.Member.MassPropertyRecalculate,
                SwRemodelProbeHost.Member.MassPropertyGetVolume,
                SwRemodelProbeHost.Member.MassPropertyGetSurfaceArea,
                SwRemodelProbeHost.Member.MassPropertyGetCenterOfMass,
                SwRemodelProbeHost.Member.MassPropertyGetPrincipalMoments,
            });
    }

    private static void MeasureOneAnalyticSolid(
        RemodelProbeContext context,
        string label,
        AnalyticSolidSpec spec,
        Dictionary<string, string> raw,
        ref bool anyMeasured,
        ref bool anyFailed)
    {
        string path = Path.Combine(context.OutputDirectory, "probe-part", $"probe-8-{label}.SLDPRT");
        RemodelProbe.AssertPartSavePath(path, context.OutputDirectory);

        RemodelProbePart? part = null;
        try
        {
            part = context.Host.BuildAnalyticSolid(spec, path);
            IMassPropertyReading? reading = context.Host.MeasureMassProperties(part);
            if (reading == null)
            {
                raw[$"{label}_status"] = "CreateMassProperty2 returned nothing";
                anyFailed = true;
                return;
            }

            reading.SetAccuracyLevel(RemodelGeometry.HigherAccuracy);
            reading.SetUseSystemUnits(true);
            bool recalculated = reading.Recalculate();
            if (!recalculated)
            {
                raw[$"{label}_status"] = "Recalculate returned false";
                anyFailed = true;
                return;
            }

            double measuredVolume = reading.GetVolume();
            double measuredArea = reading.GetSurfaceArea();
            IReadOnlyList<double>? measuredCoM = reading.GetCenterOfMass();
            IReadOnlyList<double>? measuredMoments = reading.GetPrincipalMomentsOfInertia();
            double density = reading.GetDensity();

            double exactVolume = AnalyticSolidMath.Volume(spec);
            double exactArea = AnalyticSolidMath.SurfaceArea(spec);
            double characteristicLength = AnalyticSolidMath.CharacteristicLength(spec);

            raw[$"{label}_status"] = "measured";
            raw[$"{label}_volume_rel_error"] = FormatError(AnalyticSolidMath.RelativeError(measuredVolume, exactVolume));
            raw[$"{label}_area_rel_error"] = FormatError(AnalyticSolidMath.RelativeError(measuredArea, exactArea));

            if (measuredCoM != null && measuredCoM.Count == 3)
            {
                double comError = measuredCoM
                    .Select(component => AnalyticSolidMath.NormalizedAbsoluteError(component, characteristicLength))
                    .Max();
                raw[$"{label}_com_normalized_abs_error"] = FormatError(comError);
            }
            else
            {
                raw[$"{label}_com_normalized_abs_error"] = "unreadable";
                anyFailed = true;
            }

            if (measuredMoments != null && measuredMoments.Count == 3)
            {
                double[] sortedMeasured = measuredMoments.OrderBy(moment => moment).ToArray();
                IReadOnlyList<double> exactMoments = AnalyticSolidMath.PrincipalMomentsOfInertia(spec, density);
                double maxMomentError = 0.0;
                for (int i = 0; i < 3; i++)
                {
                    maxMomentError = Math.Max(maxMomentError, AnalyticSolidMath.RelativeError(sortedMeasured[i], exactMoments[i]));
                }

                raw[$"{label}_moments_max_rel_error"] = FormatError(maxMomentError);
            }
            else
            {
                raw[$"{label}_moments_max_rel_error"] = "unreadable";
                anyFailed = true;
            }

            anyMeasured = true;
        }
        finally
        {
            if (part != null)
            {
                context.Host.ClosePart(part);
                TryDeleteFile(part.Path);
            }
        }
    }

    private static string FormatError(double value) => value.ToString("E6", CultureInfo.InvariantCulture);

    // ---- PROBE-9: force a rebuild error and inspect GetWhatsWrong's element kind -------

    private static RemodelProbeReading Probe9(RemodelProbeContext context)
    {
        const string boxFeature = "Boss-Extrude1";

        bool suppressed = context.Host.SetFeatureSuppression(context.Part, boxFeature, true);
        bool rebuilt = context.Host.ForceRebuild(context.Part);
        RemodelWhatsWrongReading whatsWrong = context.Host.ReadWhatsWrong(context.Part);

        (RemodelProbeVerdict verdict, string reason) = RemodelProbe9Logic.Decide(suppressed, whatsWrong);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["suppress_returned"] = suppressed.ToString(),
            ["rebuild_returned"] = rebuilt.ToString(),
            ["whats_wrong_count"] = whatsWrong.Count.ToString(CultureInfo.InvariantCulture),
            ["whats_wrong_call_succeeded"] = whatsWrong.CallSucceeded.ToString(),
            ["whats_wrong_element_kind"] = whatsWrong.ElementKind,
            ["reason"] = reason,
        };

        return new RemodelProbeReading(
            verdict,
            raw,
            new[]
            {
                "SetSuppression2",
                SwRemodelProbeHost.Member.ForceRebuild3,
                SwRemodelProbeHost.Member.GetWhatsWrongCount,
                SwRemodelProbeHost.Member.GetWhatsWrong,
            });
    }

    // ---- PROBE-10: the ___EndTag___ marker, and whether it survives a rename -----------

    private static RemodelProbeReading Probe10(RemodelProbeContext context)
    {
        const string folder = "Folder1";
        const string renamed = "Probe10RenamedFolder";
        const string marker = "___EndTag___";

        IReadOnlyList<string> before = context.Host.GetFeatureNames(context.Part);
        bool markerBefore = before.Any(name => name.Contains(marker));

        context.Host.SetFeatureName(context.Part, folder, renamed);

        IReadOnlyList<string> after = context.Host.GetFeatureNames(context.Part);
        string? markerAfter = after.FirstOrDefault(name => name.Contains(marker));

        (RemodelProbeVerdict verdict, string reason) = RemodelProbe10Logic.Decide(markerBefore, markerAfter, folder, renamed);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["marker_before"] = markerBefore.ToString(),
            ["marker_after"] = (markerAfter != null).ToString(),
            ["marker_name_after"] = markerAfter ?? "(none)",
            ["tree_after_rename"] = string.Join(",", after),
            ["reason"] = reason,
        };

        return new RemodelProbeReading(
            verdict, raw, new[] { SwRemodelProbeHost.Member.GetName, SwRemodelProbeHost.Member.SetName });
    }

    // ---- PROBE-11: the GetTypeName2 census ----------------------------------------------

    private static RemodelProbeReading Probe11(RemodelProbeContext context)
    {
        IReadOnlyList<string> names = context.Host.GetFeatureNames(context.Part);
        var raw = new Dictionary<string, string>(StringComparer.Ordinal);
        bool anyUnreadable = false;

        // Distinct names only: the recipe's fillet and chamfer share one (R3.7), and asking
        // twice under that name would just re-resolve to whichever of the two is reached first -
        // once is enough for the census.
        foreach (string name in names.Distinct())
        {
            string? typeName = context.Host.GetFeatureTypeName(context.Part, name);
            raw[$"type[{name}]"] = typeName ?? "(unreadable)";
            if (typeName == null)
            {
                anyUnreadable = true;
            }
        }

        RemodelProbeVerdict verdict = anyUnreadable ? RemodelProbeVerdict.Unresolved : RemodelProbeVerdict.Verified;
        raw["reason"] = anyUnreadable
            ? "at least one feature's GetTypeName2 was unreadable; an unrecognised type name gives unresolved rather than a guess."
            : "every feature in the tree answered GetTypeName2; compare the census above against "
                + "reviewer/src/swreview/checks/rms_types.yaml by hand - that table lives outside this build.";

        return new RemodelProbeReading(verdict, raw, new[] { SwRemodelProbeHost.Member.GetTypeName2 });
    }

    // ---- PROBE-12: tag, save, close, reopen, read back -----------------------------------

    private static RemodelProbeReading Probe12(RemodelProbeContext context)
    {
        const string key = "SwReviewProbe12";
        const string value = "verify-me";

        string path = Path.Combine(context.OutputDirectory, "probe-part", "probe-12-tag.SLDPRT");
        RemodelProbe.AssertPartSavePath(path, context.OutputDirectory);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal);
        RemodelProbeVerdict verdict;
        string reason;

        try
        {
            var recipe = new RemodelProbePartRecipe(new[] { new RemodelProbeFeatureStep("Box1", RemodelProbeFeatureKind.Box) });
            RemodelProbePart built = context.Host.BuildPart(recipe, path);

            int addResult = context.Host.AddCustomProperty(built, key, value);
            raw["add_result"] = addResult.ToString(CultureInfo.InvariantCulture);

            bool saved = context.Host.SaveExistingPart(built);
            raw["saved"] = saved.ToString();

            context.Host.ClosePart(built);

            RemodelProbePart reopened = context.Host.ReopenPart(path);
            try
            {
                bool found = context.Host.GetCustomProperty(reopened, key, out string? readValue, out string? resolvedValue);
                raw["found_after_reopen"] = found.ToString();
                raw["value_after_reopen"] = readValue ?? "(none)";
                raw["resolved_value_after_reopen"] = resolvedValue ?? "(none)";

                (verdict, reason) = RemodelProbe12Logic.Decide(saved, found, readValue, value);
            }
            finally
            {
                context.Host.ClosePart(reopened);
            }
        }
        finally
        {
            TryDeleteFile(path);
        }

        raw["reason"] = reason;
        return new RemodelProbeReading(
            verdict,
            raw,
            new[]
            {
                SwRemodelProbeHost.Member.CustomPropertyAdd3,
                SwRemodelProbeHost.Member.SaveAs3,
                SwRemodelProbeHost.Member.OpenDoc7,
                SwRemodelProbeHost.Member.CustomPropertyGet4,
            });
    }

    // ---- PROBE-13: File.Copy against an open .SLDPRT, and its stream fallback ----------

    private static RemodelProbeReading Probe13(RemodelProbeContext context)
    {
        string source = context.Part.Path;
        string destination = Path.Combine(
            Path.GetDirectoryName(source) ?? context.OutputDirectory, "probe-13-copy.SLDPRT");

        var raw = new Dictionary<string, string>(StringComparer.Ordinal);
        bool copySucceeded;
        bool fallbackAttempted = false;
        bool fallbackSucceeded = false;

        try
        {
            try
            {
                File.Copy(source, destination, overwrite: true);
                copySucceeded = true;
            }
            catch (Exception copyError) when (copyError is IOException || copyError is UnauthorizedAccessException)
            {
                // UnauthorizedAccessException, not only IOException: a locked file on Windows
                // surfaces as either depending on exactly how it is locked, and a real
                // SOLIDWORKS lock is not something this build can predict.
                copySucceeded = false;
                raw["file_copy_error"] = copyError.Message;
                fallbackAttempted = true;

                try
                {
                    using (var sourceStream = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                    using (var destinationStream = new FileStream(destination, FileMode.Create, FileAccess.Write))
                    {
                        sourceStream.CopyTo(destinationStream);
                    }

                    fallbackSucceeded = true;
                }
                catch (Exception fallbackError)
                {
                    raw["fallback_error"] = fallbackError.Message;
                }
            }
        }
        finally
        {
            TryDeleteFile(destination);
        }

        raw["file_copy_succeeded"] = copySucceeded.ToString();
        if (fallbackAttempted)
        {
            raw["fallback_succeeded"] = fallbackSucceeded.ToString();
        }

        (RemodelProbeVerdict verdict, string reason) = RemodelProbe13Logic.Decide(copySucceeded, fallbackSucceeded);
        raw["reason"] = reason;

        return new RemodelProbeReading(verdict, raw, Array.Empty<string>());
    }

    // ---- PROBE-20: does Description survive a reorder and a folder wrap? ---------------

    private static RemodelProbeReading Probe20(RemodelProbeContext context)
    {
        const string feature = "Shell1";
        const string folder = "Folder1";
        const string description = "probe-20 description";
        int toFolder = (int)swMoveLocation_e.swMoveToFolder;

        context.Host.SetFeatureDescription(context.Part, feature, description);
        bool moved = context.Host.ReorderFeature(context.Part, feature, folder, toFolder);
        string? after = context.Host.GetFeatureDescription(context.Part, feature);

        (RemodelProbeVerdict verdict, string reason) = RemodelProbe20Logic.Decide(moved, description, after);

        var raw = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["moved_into_folder"] = moved.ToString(),
            ["description_after"] = after ?? "(unreadable)",
            ["per_configuration"] = "not tested - the throwaway part has a single configuration",
            ["reason"] = reason,
        };

        return new RemodelProbeReading(
            verdict,
            raw,
            new[]
            {
                SwRemodelProbeHost.Member.SetDescription,
                SwRemodelProbeHost.Member.GetDescription,
                SwRemodelProbeHost.Member.ReorderFeature,
            });
    }

    // ---- PROBE-21: IEquationMgr on a part with no equations -----------------------------

    private static RemodelProbeReading Probe21(RemodelProbeContext context)
    {
        object blank = context.Host.BuildBlankDocument();
        try
        {
            int count = context.Host.GetEquationCount(blank);
            var raw = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["equation_count"] = count.ToString(CultureInfo.InvariantCulture),
            };

            if (count == 0)
            {
                raw["reason"] = "a part with no equations reports GetCount() == 0 rather than throwing.";
                return new RemodelProbeReading(
                    RemodelProbeVerdict.Verified, raw, new[] { SwRemodelProbeHost.Member.EquationGetCount });
            }

            raw["reason"] =
                $"a brand-new part reported {count.ToString(CultureInfo.InvariantCulture)} equations "
                + "instead of 0; the blank-document build must have picked up something unexpected.";
            return new RemodelProbeReading(
                RemodelProbeVerdict.Unresolved, raw, new[] { SwRemodelProbeHost.Member.EquationGetCount });
        }
        finally
        {
            context.Host.DiscardBlankDocument(blank);
        }
    }

    // ---- shared plumbing ------------------------------------------------------------------

    /// <summary>
    /// Deletes a probe's own scratch file, never letting a locked or already-gone file turn a
    /// completed probe into a failed run (the same reasoning <c>Program.TryDeleteProbePart</c>
    /// already applies to the main throwaway part).
    /// </summary>
    private static void TryDeleteFile(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
