using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T042 and T044. The stage-1 write surface of the re-modeler, asserted as an exact table
/// against contracts/guard-allowlist.md.
///
/// <see cref="ReadOnlyGuard"/> is a denylist because the reviewer's read surface is unbounded;
/// <see cref="RemodelGuard"/> is an allowlist because the re-modeler's write surface is a
/// closed set of twenty interface-qualified keys. The two layers answer different questions -
/// which member may be called at all, and (in <see cref="RemodelScope"/>) which document it
/// may be called on - because a call guard never sees the document: it is captured inside the
/// lambda at <c>SwGate.Call("GetChildren", () =&gt; component.GetChildren())</c>.
/// </summary>
public class RemodelGuardTests
{
    /// <summary>
    /// The stage-1 allowlist, exactly as contracts/guard-allowlist.md tabulates it. This
    /// array is the specification; a key added to <see cref="RemodelGuard"/> without a row
    /// here fails <see cref="AllowedKeys_AreExactlyTheStage1Allowlist"/>.
    /// </summary>
    public static readonly string[] Stage1Allowlist =
    {
        "IModelDocExtension.ReorderFeature",
        "IFeatureManager.InsertFeatureTreeFolder2",
        "IFeatureManager.EditRollback",
        "IFeature.set_Name",
        "IFeature.set_Description",
        "IFeature.Select2",
        "IEquationMgr.Add3",
        "IEquationMgr.Add2",
        "IEquationMgr.Delete",
        "IEquationMgr.set_Equation",
        "IEquationMgr.SetEquationAndConfigurationOption",
        "IModelDoc2.ForceRebuild3",
        "IModelDoc2.ClearSelection2",
        "IModelDoc2.Save3",
        "IModelDocExtension.SelectByID2",
        "ICustomPropertyManager.Add3",
        "ICustomPropertyManager.Delete2",
        "ISldWorks.SetUserPreferenceToggle",
        "ISldWorks.set_CommandInProgress",
        "ISldWorks.CloseDoc",
    };

    /// <summary>
    /// <see cref="ReadOnlyGuard.DeniedMembers"/> as this allowlist was written against it.
    /// A denial added, removed or reworded upstream fails the set assertions below rather
    /// than silently widening or narrowing the remodel surface.
    /// </summary>
    private static readonly string[] ExpectedDeniedMembers =
    {
        "EditRebuild3",
        "ForceRebuild3",
        "ForceRebuildAll",
        "Save3",
        "SaveAs3",
        "Delete2",
        "EditDelete",
        "EditSuppress2",
        "EditUnsuppress2",
        "SetSuppression2",
        "SetSuppression",
        "ModifyDefinition",
        "AccessSelections",
        "EditRollback",
        "SetSaveFlag",
    };

    /// <summary><see cref="ReadOnlyGuard.DeniedPrefixes"/> as this allowlist was written against it.</summary>
    private static readonly string[] ExpectedDeniedPrefixes =
    {
        "FeatureCut",
        "FeatureExtrusion",
        "InsertFeature",
        "SetSystemValue",
    };

    /// <summary>
    /// The five allowlist keys that needed the allowlist to pass: every other key is a member
    /// the read-only denylist never covered. This is the whole of the remodel feature's
    /// widening, one row per key, and it is asserted as a set so a denial added upstream
    /// cannot enlarge it unnoticed.
    /// </summary>
    private static readonly string[] KeysThatOverrideAReadOnlyDenial =
    {
        "IFeatureManager.InsertFeatureTreeFolder2",
        "IFeatureManager.EditRollback",
        "IModelDoc2.ForceRebuild3",
        "IModelDoc2.Save3",
        "ICustomPropertyManager.Delete2",
    };

    /// <summary>
    /// The members contracts/guard-allowlist.md excludes that <see cref="ReadOnlyGuard"/>
    /// does not already refuse, so the remodel guard has to refuse them itself: the UI undo
    /// stack (<c>EditUndo2</c> returns void, VERIFIED, so it cannot be verified, and it is
    /// shared with the engineer) and the read-only-state flag. Feature 003's T087 left these
    /// to feature 004's guard work, and 004 adds nothing to <see cref="ReadOnlyGuard"/>.
    /// </summary>
    private static readonly string[] ExpectedRemodelExclusions =
    {
        "EditUndo2",
        "EditRedo2",
        "StartRecordingUndoObject",
        "FinishRecordingUndoObject2",
        "SetReadOnlyState",
    };

    private static RemodelGuard Guard() => new RemodelGuard();

    [Fact]
    public void AllowedKeys_AreExactlyTheStage1Allowlist()
    {
        var expected = new HashSet<string>(Stage1Allowlist, StringComparer.Ordinal);
        var actual = new HashSet<string>(RemodelGuard.AllowedKeys, StringComparer.Ordinal);

        Assert.True(
            expected.SetEquals(actual),
            "The stage-1 allowlist and contracts/guard-allowlist.md disagree. Missing from the code: "
            + string.Join(", ", expected.Except(actual)) + "; missing from this test: "
            + string.Join(", ", actual.Except(expected)) + ".");
        Assert.Equal(Stage1Allowlist.Length, RemodelGuard.AllowedKeys.Count);
        Assert.Equal(20, RemodelGuard.AllowedKeys.Count);
    }

    [Theory]
    [InlineData("IModelDocExtension.ReorderFeature")]
    [InlineData("IFeatureManager.InsertFeatureTreeFolder2")]
    [InlineData("IFeatureManager.EditRollback")]
    [InlineData("IFeature.set_Name")]
    [InlineData("IFeature.set_Description")]
    [InlineData("IFeature.Select2")]
    [InlineData("IEquationMgr.Add3")]
    [InlineData("IEquationMgr.Add2")]
    [InlineData("IEquationMgr.Delete")]
    [InlineData("IEquationMgr.set_Equation")]
    [InlineData("IEquationMgr.SetEquationAndConfigurationOption")]
    [InlineData("IModelDoc2.ForceRebuild3")]
    [InlineData("IModelDoc2.ClearSelection2")]
    [InlineData("IModelDoc2.Save3")]
    [InlineData("IModelDocExtension.SelectByID2")]
    [InlineData("ICustomPropertyManager.Add3")]
    [InlineData("ICustomPropertyManager.Delete2")]
    [InlineData("ISldWorks.SetUserPreferenceToggle")]
    [InlineData("ISldWorks.set_CommandInProgress")]
    [InlineData("ISldWorks.CloseDoc")]
    public void Assert_AllowlistedKey_Passes(string key)
    {
        Guard().Assert(key);
    }

    /// <summary>
    /// Both collisions of contracts/guard-allowlist.md, resolved in both directions: the
    /// custom-property <c>Delete2</c> the reviewer's denylist refuses by bare name is allowed
    /// here, while <c>IEntity.Delete2</c> - the member that denial was written for - is not;
    /// and <c>Add3</c> is allowed on exactly the two interfaces that have a call path.
    /// </summary>
    [Fact]
    public void Assert_InterfaceCollisions_AreResolvedInBothDirections()
    {
        Guard().Assert("ICustomPropertyManager.Delete2");
        Assert.Throws<MutatingCallError>(() => Guard().Assert("IEntity.Delete2"));

        Guard().Assert("IEquationMgr.Add3");
        Guard().Assert("ICustomPropertyManager.Add3");
        Assert.Throws<MutatingCallError>(() => Guard().Assert("IConfigurationManager.Add3"));
    }

    /// <summary>
    /// Owner decision: v1 refuses a part whose tree already carries an RMS-named folder
    /// holding the wrong members, rather than dissolving and re-wrapping it. That removes
    /// the single highest-risk allowance - the one call that deletes real features on a
    /// mis-selection - from the guard entirely.
    /// </summary>
    [Fact]
    public void Assert_EditDelete_IsRefusedAndAbsentFromTheAllowlist()
    {
        Assert.DoesNotContain("IModelDoc2.EditDelete", RemodelGuard.AllowedKeys);
        Assert.DoesNotContain(
            RemodelGuard.AllowedKeys,
            key => string.Equals(CallKey.BareName(key), "EditDelete", StringComparison.OrdinalIgnoreCase));

        Assert.Throws<MutatingCallError>(() => Guard().Assert("IModelDoc2.EditDelete"));
        Assert.Throws<MutatingCallError>(() => Guard().Assert("EditDelete"));
    }

    /// <summary>
    /// The explicit exclusion list of contracts/guard-allowlist.md, one row each. Every row
    /// is refused whether it arrives interface-qualified or, for the members the read-only
    /// denylist already covers, as a bare name.
    /// </summary>
    [Theory]
    [InlineData("IModelDoc2.EditRebuild3")]
    [InlineData("EditRebuild3")]
    [InlineData("IModelDoc2.SaveAs3")]
    [InlineData("IModelDocExtension.SaveAs3")]
    [InlineData("SaveAs3")]
    [InlineData("IModelDoc2.SetSaveFlag")]
    [InlineData("SetSaveFlag")]
    [InlineData("IFeature.ModifyDefinition")]
    [InlineData("ModifyDefinition")]
    [InlineData("IModelDoc2.EditSuppress2")]
    [InlineData("EditSuppress2")]
    [InlineData("IModelDoc2.EditUnsuppress2")]
    [InlineData("EditUnsuppress2")]
    [InlineData("IFeature.SetSuppression2")]
    [InlineData("SetSuppression2")]
    [InlineData("IModelDoc2.EditUndo2")]
    [InlineData("EditUndo2")]
    [InlineData("IModelDoc2.EditRedo2")]
    [InlineData("EditRedo2")]
    [InlineData("IModelDocExtension.StartRecordingUndoObject")]
    [InlineData("StartRecordingUndoObject")]
    [InlineData("IModelDocExtension.FinishRecordingUndoObject2")]
    [InlineData("FinishRecordingUndoObject2")]
    [InlineData("IModelDoc2.SetReadOnlyState")]
    [InlineData("SetReadOnlyState")]
    [InlineData("IDimension.set_Name")]
    [InlineData("IModelDoc2.SetSystemValue")]
    [InlineData("SetSystemValue")]
    [InlineData("IModelDoc2.SetSystemValues")]
    [InlineData("IModelDocExtension.SetUserPreferenceToggle")]
    [InlineData("IFeatureManager.FeatureCut4")]
    [InlineData("FeatureCut4")]
    [InlineData("IFeatureManager.FeatureExtrusion3")]
    [InlineData("FeatureExtrusion3")]
    [InlineData("IFeatureManager.InsertFeatureChamfer")]
    [InlineData("InsertFeatureChamfer")]
    [InlineData("IFeatureManager.FeatureFillet3")]
    [InlineData("IFeatureManager.InsertMirrorFeature2")]
    [InlineData("IPartDoc.CreateFeatureFromBody3")]
    [InlineData("ISketchManager.CreateCircle")]
    public void Assert_ExcludedMember_IsRefused(string key)
    {
        Assert.Throws<MutatingCallError>(() => Guard().Assert(key));
    }

    /// <summary>
    /// <c>IDimension.set_Name</c> is refused while <c>IFeature.set_Name</c> passes: v1
    /// addresses no dimension at all (FR-030), so the entry would have no call path, which is
    /// the accidental widening <c>StartRecordingUndoObject</c> is excluded for. This is the
    /// same-member-different-interface case the qualified key exists to decide.
    /// </summary>
    [Fact]
    public void Assert_SetName_IsAllowedOnFeatureAndRefusedOnDimension()
    {
        Guard().Assert("IFeature.set_Name");
        Assert.Throws<MutatingCallError>(() => Guard().Assert("IDimension.set_Name"));
    }

    /// <summary>
    /// Anything not on the list delegates to <c>ReadOnlyGuard.Assert(BareName(key))</c>, so
    /// the remodel family's read call sites - which pass bare names exactly as the reviewer's
    /// do - keep the read-only guard's answer unchanged.
    /// </summary>
    [Theory]
    [InlineData("GetObjectByPersistReference3")]
    [InlineData("get_Name")]
    [InlineData("GetWhatsWrongCount")]
    [InlineData("Get4")]
    [InlineData("GetTypeName2")]
    [InlineData("GetSelectedObjectCount2")]
    [InlineData("GetOpenDocumentByName")]
    [InlineData("IsRolledBack")]
    [InlineData("GetSaveFlag")]
    public void Assert_BareReadMember_TakesTheReadOnlyPathAndPasses(string member)
    {
        Guard().Assert(member);
        ReadOnlyGuard.Assert(member);
    }

    [Theory]
    [InlineData("Save3")]
    [InlineData("EditRollback")]
    [InlineData("ForceRebuild3")]
    [InlineData("Delete2")]
    public void Assert_BareWriteMemberTheDenylistCovers_IsStillRefused(string member)
    {
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(() => Guard().Assert(member));
        Assert.Equal(member, refusal.MemberName);
    }

    /// <summary>
    /// The denylist's known gaps are why the write surface is keyed by interface:
    /// <c>FeatureFillet3</c> is a creation member <see cref="ReadOnlyGuard"/> never covered,
    /// so a bare key would pass. It is refused the moment it is spelled as the qualified key
    /// every write call site is required to use (<see cref="CallKey.AssertQualified"/>),
    /// which is the property this guard actually rests on.
    /// </summary>
    [Fact]
    public void Assert_BareCreationMemberTheDenylistMisses_PassesWhichIsWhyWritesAreQualified()
    {
        Guard().Assert("FeatureFillet3");
        Assert.Throws<MutatingCallError>(() => Guard().Assert("IFeatureManager.FeatureFillet3"));
        Assert.Throws<ArgumentException>(() => CallKey.AssertQualified("FeatureFillet3"));
    }

    /// <summary>The allowlist matches ordinally, so a mis-cased key fails closed.</summary>
    [Theory]
    [InlineData("imodeldoc2.save3")]
    [InlineData("IModelDoc2.SAVE3")]
    [InlineData("ifeature.set_name")]
    public void Assert_MisCasedKey_IsRefused(string key)
    {
        Assert.Throws<MutatingCallError>(() => Guard().Assert(key));
    }

    [Fact]
    public void Assert_AllowlistedKey_IsTrimmedBeforeItIsJudged()
    {
        Guard().Assert("  IModelDoc2.Save3  ");
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void Assert_MissingKey_Throws(string? key)
    {
        Assert.Throws<ArgumentException>(() => Guard().Assert(key!));
    }

    [Fact]
    public void Guard_IsAnICallGuard()
    {
        ICallGuard guard = Guard();

        guard.Assert("IModelDoc2.Save3");
        Assert.Throws<MutatingCallError>(() => guard.Assert("IModelDoc2.EditDelete"));
    }

    // ---- set equality against the read-only denied surface -------------------------------

    [Fact]
    public void ReadOnlyGuard_DeniedSurface_IsExactlyWhatThisAllowlistWasWrittenAgainst()
    {
        var expectedMembers = new HashSet<string>(ExpectedDeniedMembers, StringComparer.OrdinalIgnoreCase);
        var expectedPrefixes = new HashSet<string>(ExpectedDeniedPrefixes, StringComparer.OrdinalIgnoreCase);

        Assert.True(
            expectedMembers.SetEquals(ReadOnlyGuard.DeniedMembers),
            "ReadOnlyGuard.DeniedMembers changed; re-read contracts/guard-allowlist.md before touching "
            + "the stage-1 allowlist.");
        Assert.True(
            expectedPrefixes.SetEquals(ReadOnlyGuard.DeniedPrefixes),
            "ReadOnlyGuard.DeniedPrefixes changed; re-read contracts/guard-allowlist.md before touching "
            + "the stage-1 allowlist.");
    }

    /// <summary>
    /// The set assertion contracts/guard-allowlist.md asks for: the allowlist keys that the
    /// read-only denied surface refuses - every key that needed the allowlist to pass - are
    /// exactly five, so a denial added upstream cannot silently widen the remodel surface,
    /// and an allowlist key added here cannot silently override one.
    /// </summary>
    [Fact]
    public void Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive()
    {
        var overriding = new HashSet<string>(
            RemodelGuard.AllowedKeys.Where(key => ReadOnlyGuardRefuses(CallKey.BareName(key))),
            StringComparer.Ordinal);
        var expected = new HashSet<string>(KeysThatOverrideAReadOnlyDenial, StringComparer.Ordinal);

        Assert.True(
            expected.SetEquals(overriding),
            "The allowlist keys that override a read-only denial are now: "
            + string.Join(", ", overriding.OrderBy(k => k, StringComparer.Ordinal)) + ".");
    }

    /// <summary>
    /// The remodel guard's own small refusal set exists only for the members the read-only
    /// denylist does not cover. If one of them is denied upstream one day, it must be dropped
    /// from here rather than kept in two places.
    /// </summary>
    [Fact]
    public void RemodelExclusions_AreOnlyMembersTheReadOnlyGuardDoesNotAlreadyRefuse()
    {
        var expected = new HashSet<string>(ExpectedRemodelExclusions, StringComparer.OrdinalIgnoreCase);

        Assert.True(
            expected.SetEquals(RemodelGuard.ExcludedMembers),
            "RemodelGuard.ExcludedMembers is now: " + string.Join(", ", RemodelGuard.ExcludedMembers) + ".");

        foreach (string member in RemodelGuard.ExcludedMembers)
        {
            Assert.False(
                ReadOnlyGuardRefuses(member),
                member + " is already refused by ReadOnlyGuard; drop it from RemodelGuard.ExcludedMembers.");
        }
    }

    [Fact]
    public void Allowlist_AndTheRemodelExclusions_DoNotOverlap()
    {
        foreach (string key in RemodelGuard.AllowedKeys)
        {
            Assert.DoesNotContain(
                RemodelGuard.ExcludedMembers,
                member => string.Equals(member, CallKey.BareName(key), StringComparison.OrdinalIgnoreCase));
        }
    }

    [Fact]
    public void Allowlist_IsWrittenEntirelyInInterfaceQualifiedKeys()
    {
        foreach (string key in RemodelGuard.AllowedKeys)
        {
            Assert.True(CallKey.IsQualified(key), key + " is not an interface-qualified key.");
        }
    }

    private static bool ReadOnlyGuardRefuses(string member)
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
}

/// <summary>
/// T044. <c>AssertSaveTarget</c> is called before <c>IModelDoc2.Save3</c> even though
/// <c>Save3</c> takes no filename (VERIFIED): the source is unreachable structurally - the
/// copy is opened at its own path and <c>Save3</c> saves whatever document it is called on,
/// with no path to redirect it - and this assertion is what the suite pins and what the run
/// report cites.
/// </summary>
public class RemodelSaveTargetTests
{
    private const string RunDirectory = @"C:\runs\20260916-142201-bracket-remodel";
    private const string CopyPath = @"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT";
    private const string SourcePath = @"C:\vault\projects\bracket.SLDPRT";

    [Fact]
    public void AssertSaveTarget_ThisRunsCopy_Passes()
    {
        RemodelScope.AssertSaveTarget(CopyPath, CopyPath, RunDirectory, SourcePath);
    }

    [Theory]
    // Outside this run's folder.
    [InlineData(@"C:\runs\bracket-RMS.SLDPRT")]
    [InlineData(@"C:\vault\projects\copy\bracket-RMS.SLDPRT")]
    // Another run's copy.
    [InlineData(@"C:\runs\20260916-150000-bracket-remodel\copy\bracket-RMS.SLDPRT")]
    // A path containing '..' before canonicalization, even one that canonicalizes to the copy.
    [InlineData(@"C:\runs\20260916-142201-bracket-remodel\copy\..\copy\bracket-RMS.SLDPRT")]
    [InlineData(@"C:\runs\20260916-142201-bracket-remodel\copy\..\..\..\vault\projects\bracket.SLDPRT")]
    // The source itself.
    [InlineData(SourcePath)]
    // Not a part file, or no extension at all.
    [InlineData(@"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.sldasm")]
    [InlineData(@"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.slddrw")]
    [InlineData(@"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS")]
    [InlineData(@"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.png")]
    // The copy path spelled differently: another case, or an 8.3 short name.
    [InlineData(@"C:\runs\20260916-142201-bracket-remodel\copy\BRACKET-RMS.SLDPRT")]
    [InlineData(@"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.sldprt")]
    [InlineData(@"C:\runs\202609~1\copy\bracket-RMS.SLDPRT")]
    [InlineData(@"C:\RUNS\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT")]
    public void AssertSaveTarget_AnythingElse_IsRefused(string path)
    {
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(
            () => RemodelScope.AssertSaveTarget(path, CopyPath, RunDirectory, SourcePath));

        Assert.Equal("Save3", refusal.MemberName);
        Assert.False(string.IsNullOrWhiteSpace(refusal.Message));
    }

    [Fact]
    public void AssertSaveTarget_TheSource_IsRefusedByName()
    {
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(
            () => RemodelScope.AssertSaveTarget(SourcePath, CopyPath, RunDirectory, SourcePath));

        Assert.Contains("source", refusal.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void AssertSaveTarget_PathWithDotDot_IsRefusedBeforeCanonicalization()
    {
        MutatingCallError refusal = Assert.Throws<MutatingCallError>(
            () => RemodelScope.AssertSaveTarget(
                @"C:\runs\20260916-142201-bracket-remodel\copy\..\copy\bracket-RMS.SLDPRT",
                CopyPath,
                RunDirectory,
                SourcePath));

        Assert.Contains("..", refusal.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void AssertSaveTarget_MissingPath_Throws(string? path)
    {
        Assert.Throws<ArgumentException>(
            () => RemodelScope.AssertSaveTarget(path!, CopyPath, RunDirectory, SourcePath));
    }

    [Fact]
    public void AssertSaveTarget_CopyOutsideTheRunFolder_RefusesEvenThatCopy()
    {
        Assert.Throws<MutatingCallError>(() => RemodelScope.AssertSaveTarget(
            @"C:\elsewhere\bracket-RMS.SLDPRT",
            @"C:\elsewhere\bracket-RMS.SLDPRT",
            RunDirectory,
            SourcePath));
    }
}
