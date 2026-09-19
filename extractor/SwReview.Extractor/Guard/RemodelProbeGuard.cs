using System;
using System.Collections.Generic;
using SwReview.Extractor.Rms;

namespace SwReview.Extractor.Guard;

/// <summary>
/// T032. The guard <c>probe remodel</c> builds its gate with: <see cref="ReadOnlyGuard"/> plus
/// exactly the members needed to build the throwaway part the probes measure - never the
/// stage-1 <see cref="RemodelGuard"/> allowlist, which refuses the whole feature-creation
/// family on purpose (contracts/guard-allowlist.md), and never a document the engineer has
/// open, because <c>probe remodel</c> refuses to run while one is (research.md Phase 2).
///
/// Written as an exemption over the read-only guard, exactly as <see cref="SuppressTestGuard"/>
/// is: the probe's mutation surface is small and closed (one throwaway part, in the run
/// folder, never the engineer's document), so the exemption list is short, and everything
/// <see cref="ReadOnlyGuard"/> already refuses for another reason - <c>Save3</c>,
/// <c>EditDelete</c>, <c>SetSuppression2</c>, every other <c>FeatureExtrusion*</c>/
/// <c>FeatureCut*</c>/<c>InsertFeature*</c> variant this probe never calls - stays refused.
///
/// <c>FeatureFillet3</c> needs no entry here: it is not on <see cref="ReadOnlyGuard"/>'s
/// denylist or denied-prefix list at all, so it already passes underneath this guard exactly
/// as it does under a plain <see cref="ReadOnlyGuard"/>. It is exercised through
/// <see cref="Sw.SwGate.Call{T}"/> regardless, for the same audit-trail reason every other
/// interop call in the product is.
/// </summary>
public sealed class RemodelProbeGuard : ICallGuard
{
    /// <summary>
    /// The whole exemption set: one member per recipe step
    /// (<see cref="RemodelProbePartRecipe.Default"/>) that <see cref="ReadOnlyGuard"/> would
    /// otherwise refuse, plus the two run-scoped system settings <see cref="RemodelSystemToggles"/>
    /// sets and restores in a <c>finally</c> around the whole probe run.
    /// </summary>
    private static readonly HashSet<string> ExemptMembers = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        // The box: IFeatureManager.FeatureExtrusion3 (denied by the FeatureExtrusion* prefix).
        "FeatureExtrusion3",

        // The cut: IFeatureManager.FeatureCut4 (denied by the FeatureCut* prefix).
        "FeatureCut4",

        // The chamfer and the shell: IFeatureManager.InsertFeatureChamfer and
        // IModelDoc2.InsertFeatureShell (both denied by the InsertFeature* prefix).
        "InsertFeatureChamfer",
        "InsertFeatureShell",

        // The one folder: IFeatureManager.InsertFeatureTreeFolder2 (denied by the same prefix).
        "InsertFeatureTreeFolder2",

        // Committing each step so the next one sees a rebuilt tree.
        "ForceRebuild3",

        // Persisting the throwaway part into the run folder. There is no engineer's source to
        // protect here - the document was created this session - so SaveAs3 is exempted
        // outright rather than routed through RemodelScope.AssertSaveTarget, which exists to
        // protect a source that this probe never opens. RemodelProbe.AssertPartSavePath is the
        // narrower check this probe uses instead: the target must be inside the run folder and
        // spelled ".SLDPRT".
        "SaveAs3",

        // The three user-preference toggles and the run-scoped modal-suppression flag of
        // PROBE-1, restored in a finally by RemodelSystemToggles.Within - the same qualified
        // keys contracts/guard-allowlist.md gives the stage-1 allowlist, read from there rather
        // than duplicated so the two guards cannot spell them differently.
        RemodelSystemToggles.ToggleMember,
        RemodelSystemToggles.CommandInProgressMember,

        // PROBE-9 (tasks.md T038): IFeature.SetSuppression2, the same call SwSuppressTarget
        // makes, exempted here for exactly one purpose - suppressing the throwaway part's box
        // feature so every downstream feature fails to rebuild, which is the only deterministic
        // way to force a real GetWhatsWrong reading without guessing at one. Never called on
        // anything but a feature this probe run itself built, and never un-suppressed
        // afterward: the part is discarded (or kept for inspection with --keep-part) either way.
        "SetSuppression2",
    };

    /// <inheritdoc />
    public void Assert(string interopMemberName)
    {
        if (!string.IsNullOrWhiteSpace(interopMemberName)
            && ExemptMembers.Contains(interopMemberName.Trim()))
        {
            return;
        }

        // Everything else - including a missing member name - is the read-only guard's answer.
        ReadOnlyGuard.Assert(interopMemberName);
    }
}
