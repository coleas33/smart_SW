using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Guard;

/// <summary>
/// T043. The guard the re-modeler's gate is built with: an <see cref="ICallGuard"/> allowlist
/// over interface-qualified keys (contracts/guard-allowlist.md).
///
/// <see cref="ReadOnlyGuard"/> is a denylist because the reviewer's read surface is unbounded
/// and grows every phase. The re-modeler is the inverse: its write surface is the closed set
/// of twenty keys in <see cref="AllowedKeys"/>, and it is exactly the workload that finds a
/// denylist's gaps - the read-only list blocked <c>InsertFeatureTreeFolder2</c> through its
/// <c>InsertFeature</c> prefix while leaving <c>FeatureFillet3</c>, <c>FeatureRevolve2</c>,
/// <c>InsertPart3</c> and <c>SetSuppression2</c>'s neighbours wide open. Decision 21A
/// (2026-09-25) closed that creation family in <see cref="ReadOnlyGuard"/>, but a denylist still
/// cannot enumerate a write surface: <c>IFeatureManager.MoveToFolder</c> and <c>IModelDoc2.Save</c>
/// pass it as bare names.
///
/// Three answers, in this order:
///   1. a key on <see cref="AllowedKeys"/>, matched <b>ordinally</b> so a mis-spelling fails
///      closed rather than widening the surface, returns;
///   2. a member on <see cref="ExcludedMembers"/> is refused however it is spelled;
///   3. any other interface-qualified key is refused, because a write call site names an
///      interface and the allowlist is the whole of the write surface; and
///   4. a bare member name - what the remodel family's read call sites pass, exactly as the
///      reviewer's do - is <see cref="ReadOnlyGuard"/>'s answer, unchanged.
///
/// This guard adds nothing to <see cref="ReadOnlyGuard"/> and reads nothing from it but the
/// answer to <c>Assert</c>. Stage 2 gets a second, additive allowlist reviewed on its own;
/// this list is never widened to accommodate it.
/// </summary>
public sealed class RemodelGuard : ICallGuard
{
    /// <summary>
    /// The stage-1 write surface, exactly as contracts/guard-allowlist.md tabulates it. Every
    /// entry has a call path: an entry without one is the accidental widening the allowlist
    /// exists to prevent, which is why <c>IDimension.set_Name</c> and
    /// <c>StartRecordingUndoObject</c> are absent.
    /// </summary>
    private static readonly HashSet<string> AllowedKeySet = new HashSet<string>(StringComparer.Ordinal)
    {
        // The only move operation; location is Before = 2 or After = 3.
        "IModelDocExtension.ReorderFeature",

        // Create a folder around the current contiguous selection, Containing = 2. The one
        // exception to "stage 1 creates nothing".
        "IFeatureManager.InsertFeatureTreeFolder2",

        // Roll the bar to the end at open, ToEnd = 1.
        "IFeatureManager.EditRollback",

        // Folder naming and duplicate-feature-name repair, and nothing else.
        "IFeature.set_Name",
        "IFeature.set_Description",

        // Build the contiguous selection a folder wraps.
        "IFeature.Select2",

        // The verified equation helper: Add3 then Add2, set_Equation then
        // SetEquationAndConfigurationOption for the op: "set" repair path (FR-029), and
        // Delete as the inverse of an add.
        "IEquationMgr.Add3",
        "IEquationMgr.Add2",
        "IEquationMgr.Delete",
        "IEquationMgr.set_Equation",
        "IEquationMgr.SetEquationAndConfigurationOption",

        // The one rebuild call, the selection clearing around every selection-based
        // operation, and the single save - which takes no filename (VERIFIED) and is made
        // behind RemodelScope.AssertSaveTarget.
        "IModelDoc2.ForceRebuild3",
        "IModelDoc2.ClearSelection2",
        "IModelDoc2.Save3",

        // Selection where Select2 is not enough.
        "IModelDocExtension.SelectByID2",

        // The session tag: written at open, removed at close. Delete2 here is the collision
        // the qualified key exists for - the read-only denial of the bare name was written
        // for IEntity.Delete2.
        "ICustomPropertyManager.Add3",
        "ICustomPropertyManager.Delete2",

        // The three user-preference toggles (10, 77, 329) and the run-scoped modal
        // suppression flag of PROBE-1, all restored in a finally. CommandInProgress is a
        // property rather than a swUserPreferenceToggle_e value, so it needs its own key.
        "ISldWorks.SetUserPreferenceToggle",
        "ISldWorks.set_CommandInProgress",

        // Close the tagged copy.
        "ISldWorks.CloseDoc",
    };

    /// <summary>
    /// The members contracts/guard-allowlist.md excludes that <see cref="ReadOnlyGuard"/>
    /// does not already refuse, so this guard refuses them itself, qualified or bare.
    ///
    /// The UI undo stack is shared with the engineer and <c>EditUndo2</c> returns <b>void</b>
    /// (VERIFIED), so a call to it cannot be verified; <c>StartRecordingUndoObject</c> and
    /// <c>FinishRecordingUndoObject2</c> are the mechanism this design decided not to rely on,
    /// and an unused allowlist entry is the accidental widening the allowlist exists to
    /// prevent; <c>SetReadOnlyState</c> changes a file's writability behind the engineer.
    /// Feature 003 (tasks T087) left these four families to feature 004's guard work, and 004
    /// adds nothing to <see cref="ReadOnlyGuard"/>, so they are refused here.
    ///
    /// Everything else in that exclusion table is already refused: by <see cref="ReadOnlyGuard"/>
    /// for a bare name (<c>SaveAs3</c>, <c>SetSaveFlag</c>, <c>EditRebuild3</c>,
    /// <c>ModifyDefinition</c>, the suppression members, <c>SetSystemValue*</c>, the
    /// <c>FeatureCut*</c> / <c>FeatureExtrusion*</c> / <c>InsertFeature*</c> families and, since
    /// decision 21A, the rest of the creation family), and by
    /// rule 3 above for any interface-qualified key that is not on the allowlist -
    /// <c>IModelDoc2.EditDelete</c>, <c>IDimension.set_Name</c>, <c>IEntity.Delete2</c> and
    /// the rest of the creation family among them.
    /// </summary>
    private static readonly HashSet<string> ExcludedMemberSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "EditUndo2",
        "EditRedo2",
        "StartRecordingUndoObject",
        "FinishRecordingUndoObject2",
        "SetReadOnlyState",
    };

    /// <summary>The stage-1 allowlist, for reading: the tests assert it as an exact table.</summary>
    public static readonly IReadOnlyCollection<string> AllowedKeys = AllowedKeySet;

    /// <summary>The members this guard refuses itself, for reading.</summary>
    public static readonly IReadOnlyCollection<string> ExcludedMembers = ExcludedMemberSet;

    /// <summary>
    /// True when <paramref name="key"/> is one of the stage-1 write keys - the question
    /// "was that call a write?", asked by the tool service's remodel observer so the log
    /// records a target path for every mutating call and for nothing else (T058).
    ///
    /// It is a lookup on the same set <see cref="Assert"/> uses, ordinal and O(1), rather than
    /// a scan of <see cref="AllowedKeys"/>: it runs inside every gated interop call, on the
    /// SOLIDWORKS thread.
    /// </summary>
    public static bool IsAllowlisted(string? key) =>
        !string.IsNullOrWhiteSpace(key) && AllowedKeySet.Contains(key!.Trim());

    /// <inheritdoc />
    public void Assert(string interopMemberName)
    {
        if (string.IsNullOrWhiteSpace(interopMemberName))
        {
            throw new ArgumentException(
                "An interop member name is required.", nameof(interopMemberName));
        }

        string key = interopMemberName.Trim();

        if (AllowedKeySet.Contains(key))
        {
            return;
        }

        string member = CallKey.BareName(key);

        if (ExcludedMemberSet.Contains(member))
        {
            throw new MutatingCallError(
                key,
                $"{key} is excluded from the stage-1 re-modeler surface by name "
                + "(contracts/guard-allowlist.md).");
        }

        if (CallKey.IsQualified(key))
        {
            throw new MutatingCallError(
                key,
                $"{key} is not on the stage-1 re-modeler allowlist. The re-modeler's write "
                + "surface is a closed set (contracts/guard-allowlist.md); stage 2 gets its "
                + "own additive list.");
        }

        // A bare member name is a read call site, in the remodel family exactly as in the
        // reviewer's. The read-only rules apply to it unchanged.
        ReadOnlyGuard.Assert(key);
    }
}
