using System;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T050. The suppress-test is the only mutation path in the product, and this guard is what
/// keeps it one: the read-only denylist minus exactly two members (research R6). Every other
/// refusal the read-only guard makes must survive, including the ones that look harmless next
/// to a suppression - ForceRebuildAll rebuilds every open document, EditRollback moves the
/// rollback bar, SetSaveFlag marks the document dirty behind the engineer's back.
/// </summary>
public class SuppressTestGuardTests
{
    /// <summary>The whole exemption set. Two members, and the list is the specification.</summary>
    private static readonly string[] Exempt =
    {
        "SetSuppression2",
        "ForceRebuild3",
    };

    /// <summary>
    /// Everything the read-only guard refuses today, minus the exemptions: the named members
    /// and one example per denied feature-creation family. A member added to
    /// <see cref="ReadOnlyGuard"/> belongs here too.
    /// </summary>
    private static readonly string[] StillRefused =
    {
        "EditRebuild3",
        "ForceRebuildAll",
        "Save3",
        "SaveAs3",
        "Delete2",
        "EditDelete",
        "EditSuppress2",
        "EditUnsuppress2",
        "SetSuppression",
        "ModifyDefinition",
        "AccessSelections",
        "EditRollback",
        "SetSaveFlag",
        "FeatureCut4",
        "FeatureExtrusion3",
        "InsertFeatureChamfer",
        "SetSystemValue",
    };

    /// <summary>Readers the suppress-test itself makes, which must keep passing.</summary>
    private static readonly string[] Readers =
    {
        "GetChildren",
        "GetSuppression2",
        "IsSuppressed2",
        "GetWhatsWrongCount",
        "GetWhatsWrong",
        "GetSaveFlag",
        "IsRolledBack",
        "IsSamePersistentID",
        "GetPersistReference3",
    };

    public static TheoryData<string> ExemptMembers => Rows(Exempt);

    public static TheoryData<string> RefusedMembers => Rows(StillRefused);

    public static TheoryData<string> ReaderMembers => Rows(Readers);

    [Theory]
    [MemberData(nameof(ExemptMembers))]
    public void Assert_ExemptMember_Passes(string member)
    {
        new SuppressTestGuard().Assert(member);
    }

    [Theory]
    [MemberData(nameof(RefusedMembers))]
    public void Assert_EverythingElseTheReadOnlyGuardRefuses_StillThrows(string member)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => new SuppressTestGuard().Assert(member));

        Assert.Equal(member, error.MemberName);
    }

    [Theory]
    [MemberData(nameof(ReaderMembers))]
    public void Assert_Reader_Passes(string member)
    {
        new SuppressTestGuard().Assert(member);
    }

    /// <summary>
    /// The "exactly" in "exactly two members": for every member these tests know about, this
    /// guard and the read-only guard agree unless the member is exempt.
    /// </summary>
    [Fact]
    public void Assert_DiffersFromTheReadOnlyGuardOnExactlyTheExemptMembers()
    {
        var guard = new SuppressTestGuard();

        foreach (string member in Exempt)
        {
            Assert.True(ReadOnlyRefuses(member), $"{member} is only worth exempting if the read-only guard refuses it.");
            guard.Assert(member);
        }

        foreach (string member in StillRefused)
        {
            Assert.True(ReadOnlyRefuses(member));
            Assert.Throws<MutatingCallError>(() => guard.Assert(member));
        }

        foreach (string member in Readers)
        {
            Assert.False(ReadOnlyRefuses(member));
            guard.Assert(member);
        }
    }

    [Fact]
    public void Assert_IsCaseInsensitive()
    {
        var guard = new SuppressTestGuard();

        guard.Assert("setsuppression2");
        guard.Assert("FORCEREBUILD3");
        Assert.Throws<MutatingCallError>(() => guard.Assert("save3"));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void Assert_MissingMemberName_Throws(string? member)
    {
        Assert.Throws<ArgumentException>(() => new SuppressTestGuard().Assert(member!));
    }

    /// <summary>The gate the suppress-test command builds: the two members go through, and
    /// nothing else the read-only guard refuses does.</summary>
    [Fact]
    public void SwGate_BuiltWithThisGuard_RunsTheSuppressionCallsAndRefusesTheRest()
    {
        var gate = new SwGate(new CircuitBreaker(), new SuppressTestGuard());

        Assert.Equal(1, gate.Call("SetSuppression2", () => 1));
        Assert.Equal(2, gate.Call("ForceRebuild3", () => 2));
        Assert.Throws<MutatingCallError>(() => gate.Call<int>("Save3", () => 3));
        Assert.Throws<MutatingCallError>(() => gate.Call<int>("ForceRebuildAll", () => 4));
    }

    private static bool ReadOnlyRefuses(string member)
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

    private static TheoryData<string> Rows(string[] members)
    {
        var rows = new TheoryData<string>();
        foreach (string member in members)
        {
            rows.Add(member);
        }

        return rows;
    }
}
