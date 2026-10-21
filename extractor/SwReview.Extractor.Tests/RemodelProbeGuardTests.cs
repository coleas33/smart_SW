using SwReview.Extractor.Guard;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>Decision 160A: the probe's run-scoped exemption matches the host's exact spellings.</summary>
public class RemodelProbeGuardTests
{
    [Theory]
    [InlineData("NewDocument")]
    [InlineData("MoveToFolder")]
    [InlineData("ISldWorks.OpenDoc7")]
    [InlineData("ForceRebuild3")]
    [InlineData("SaveAs3")]
    [InlineData("ISldWorks.SetUserPreferenceToggle")]
    [InlineData("ISldWorks.set_CommandInProgress")]
    [InlineData("SetSuppression2")]
    [InlineData("IMassProperty2.SetOverrideOptions")]
    [InlineData("IMassPropertyOverrideOptions.set_OverrideMass")]
    [InlineData("IMassPropertyOverrideOptions.set_OverrideCenterOfMass")]
    [InlineData("IMassPropertyOverrideOptions.set_OverrideMomentsOfInertia")]
    [InlineData("IMassPropertyOverrideOptions.SetOverrideMassValue")]
    [InlineData("IMassPropertyOverrideOptions.SetOverrideCenterOfMassValue")]
    [InlineData("IMassPropertyOverrideOptions.SetOverridePrincipalMomentsOfInertia")]
    public void ARunScopedMemberPassesExactlyAndACaseVariantIsRefused(string member)
    {
        var guard = new RemodelProbeGuard();
        guard.Assert(member);
        string variant = member.ToLowerInvariant();
        Assert.NotEqual(member, variant);
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(() => guard.Assert(variant));
        Assert.Equal(variant, refusal.MemberName);
    }

    /// <summary>
    /// ...and so do the throwaway part's creation members, since the review of decision 160A: matched ordinally,
    /// as the bare names the probe host gates them by are spelled, so a case variant of one is the read-only
    /// guard's answer, which refuses every one of them.
    /// </summary>
    [Theory]
    [InlineData("FeatureExtrusion3")]
    [InlineData("FeatureCut4")]
    [InlineData("FeatureFillet3")]
    [InlineData("InsertFeatureChamfer")]
    [InlineData("InsertFeatureShell")]
    [InlineData("InsertFeatureTreeFolder2")]
    [InlineData("InsertSketch")]
    [InlineData("CreateCircleByRadius")]
    public void ACreationMemberPassesExactlyAndACaseVariantIsRefused(string member)
    {
        var guard = new RemodelProbeGuard();
        guard.Assert(member);
        string variant = member.ToLowerInvariant();
        Assert.NotEqual(member, variant);
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(() => guard.Assert(variant));
        Assert.Equal(variant, refusal.MemberName);
    }
}
