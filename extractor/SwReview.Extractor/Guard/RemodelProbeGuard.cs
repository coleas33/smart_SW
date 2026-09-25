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
/// folder, never the engineer's document), so the exemption lists are short, and everything
/// <see cref="ReadOnlyGuard"/> already refuses for another reason - <c>Save3</c>,
/// <c>EditDelete</c>, every other <c>FeatureExtrusion*</c>/<c>FeatureCut*</c>/<c>InsertFeature*</c>
/// variant and every other member of the creation family this probe never calls - stays refused.
///
/// Decision 21A (feature 004, 2026-09-25) closed the creation family in <see cref="ReadOnlyGuard"/>,
/// so the throwaway part's own creation members are gathered in one named set,
/// <see cref="ThrowawayPartCreationMembers"/>, and <c>ThrowawayPartExemptionTests</c> ties it to the
/// probe's scope: it is exactly the creation members <c>SwRemodelProbeHost</c> gates that
/// <see cref="ReadOnlyGuard"/> refuses, no other gate the product builds exempts any of them, and
/// this guard is built in exactly one place, <c>probe remodel</c>'s gate. Every member is still
/// exercised through <see cref="Sw.SwGate.Call{T}"/>, for the audit trail every other interop call
/// in the product leaves.
/// </summary>
public sealed class RemodelProbeGuard : ICallGuard
{
    /// <summary>
    /// The creation members the throwaway part is built with (<see cref="RemodelProbePartRecipe.Default"/>
    /// and PROBE-8's analytic solids), matched as the bare names <c>SwRemodelProbeHost</c> gates them
    /// under, so an interface-qualified spelling of any of them is still refused. Each one is refused
    /// by <see cref="ReadOnlyGuard"/>; the comment says by what.
    /// </summary>
    private static readonly HashSet<string> ThrowawayPartCreationMemberSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        // The box, and PROBE-8's box and cylinder: IFeatureManager.FeatureExtrusion3 (the
        // FeatureExtrusion* prefix).
        "FeatureExtrusion3",

        // The cut: IFeatureManager.FeatureCut4 (the FeatureCut* prefix).
        "FeatureCut4",

        // The fillet: IFeatureManager.FeatureFillet3 (decision 21A's generated table).
        "FeatureFillet3",

        // The chamfer and the shell: IFeatureManager.InsertFeatureChamfer and
        // IModelDoc2.InsertFeatureShell (both the InsertFeature* prefix).
        "InsertFeatureChamfer",
        "InsertFeatureShell",

        // The one folder: IFeatureManager.InsertFeatureTreeFolder2 (the same prefix).
        "InsertFeatureTreeFolder2",

        // Opening and closing every profile sketch: ISketchManager.InsertSketch, refused because
        // decision 21A denies the bare name IModelDoc2.InsertSketch shares with it.
        "InsertSketch",

        // PROBE-8's cylinder profile: ISketchManager.CreateCircleByRadius, refused because decision
        // 21A denies the bare name IModelDoc2.CreateCircleByRadius shares with it.
        "CreateCircleByRadius",
    };

    /// <summary>
    /// The rest of the exemption: one rebuild per recipe step, the part's save into the run folder,
    /// the run-scoped system settings <see cref="RemodelSystemToggles"/> sets and restores in a
    /// <c>finally</c> around the whole probe run, and PROBE-9's one suppression.
    /// </summary>
    private static readonly HashSet<string> RunScopedMemberSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
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

    /// <summary>
    /// The throwaway part's creation members, for reading: the tests pin the set to the probe
    /// host's own calls and assert that no other gate exempts any of them (decision 21A).
    /// </summary>
    public static readonly IReadOnlyCollection<string> ThrowawayPartCreationMembers = ThrowawayPartCreationMemberSet;

    /// <inheritdoc />
    public void Assert(string interopMemberName)
    {
        if (!string.IsNullOrWhiteSpace(interopMemberName))
        {
            string member = interopMemberName.Trim();
            if (ThrowawayPartCreationMemberSet.Contains(member) || RunScopedMemberSet.Contains(member))
            {
                return;
            }
        }

        // Everything else - including a missing member name - is the read-only guard's answer.
        ReadOnlyGuard.Assert(interopMemberName);
    }
}
