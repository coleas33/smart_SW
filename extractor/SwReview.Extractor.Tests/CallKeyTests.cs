using System;
using SwReview.Extractor.Guard;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T040. The remodel guard allowlists <c>Interface.Member</c> keys, not bare member names,
/// because bare names collide and both halves of the collision are real on 2024 SP5:
/// <c>ICustomPropertyManager.Delete2</c> (the session-tag delete) is refused today because
/// <see cref="ReadOnlyGuard"/> denies the bare name <c>Delete2</c>, which was meant for
/// <c>IEntity.Delete2</c>; and an allowlist entry written as <c>"Add3"</c> would silently
/// permit <c>ICustomPropertyManager.Add3</c> as well as <c>IEquationMgr.Add3</c>
/// (contracts/guard-allowlist.md, "Keys are interface-qualified").
///
/// Only the remodel <b>write</b> call sites use qualified keys. The reviewer's existing
/// <c>SwGate.Call("GetChildren", ...)</c> sites, and the remodel family's own read sites,
/// keep bare names - so <see cref="CallKey.BareName"/> returns a bare name unchanged, and
/// <c>GuardTests</c> and <c>SwGateTests</c> stay green with no edits.
/// </summary>
public class CallKeyTests
{
    [Theory]
    [InlineData("IEquationMgr", "Add3", "IEquationMgr.Add3")]
    [InlineData("ICustomPropertyManager", "Add3", "ICustomPropertyManager.Add3")]
    [InlineData("ICustomPropertyManager", "Delete2", "ICustomPropertyManager.Delete2")]
    [InlineData("IModelDocExtension", "ReorderFeature", "IModelDocExtension.ReorderFeature")]
    [InlineData("IFeature", "set_Name", "IFeature.set_Name")]
    [InlineData("ISldWorks", "set_CommandInProgress", "ISldWorks.set_CommandInProgress")]
    public void QualifiedKey_JoinsTheInterfaceAndTheMember(string iface, string member, string expected)
    {
        Assert.Equal(expected, CallKey.QualifiedKey(iface, member));
    }

    [Theory]
    [InlineData("IEquationMgr", "Add3")]
    [InlineData("IModelDoc2", "Save3")]
    [InlineData("IEntity", "Delete2")]
    public void QualifiedKey_RoundTrips(string iface, string member)
    {
        string key = CallKey.QualifiedKey(iface, member);

        Assert.Equal(iface, CallKey.InterfaceName(key));
        Assert.Equal(member, CallKey.BareName(key));
        Assert.True(CallKey.IsQualified(key));
    }

    [Fact]
    public void QualifiedKey_TrimsBothParts()
    {
        Assert.Equal("IModelDoc2.Save3", CallKey.QualifiedKey("  IModelDoc2 ", " Save3  "));
    }

    [Theory]
    [InlineData("IModelDoc2.Save3", "Save3")]
    [InlineData("ICustomPropertyManager.Delete2", "Delete2")]
    [InlineData("IFeature.set_Description", "set_Description")]
    [InlineData(" IEquationMgr.SetEquationAndConfigurationOption ", "SetEquationAndConfigurationOption")]
    public void BareName_QualifiedKey_ReturnsTheMember(string key, string expected)
    {
        Assert.Equal(expected, CallKey.BareName(key));
    }

    /// <summary>
    /// The reviewer's read sites - hundreds of them - pass bare names, and the remodel
    /// family's own read sites do too. BareName has to be the identity on those, or the
    /// guard's delegation to <see cref="ReadOnlyGuard"/> would change what it refuses.
    /// </summary>
    [Theory]
    [InlineData("GetChildren")]
    [InlineData("GetObjectByPersistReference3")]
    [InlineData("get_Name")]
    [InlineData("Save3")]
    public void BareName_UnqualifiedKey_ReturnsItUnchanged(string member)
    {
        Assert.Equal(member, CallKey.BareName(member));
        Assert.False(CallKey.IsQualified(member));
    }

    [Fact]
    public void BareName_SeveralSeparators_ReturnsTheLastSegment()
    {
        Assert.Equal("Save3", CallKey.BareName("SwReview.IModelDoc2.Save3"));
    }

    [Theory]
    [InlineData(null, "Save3")]
    [InlineData("", "Save3")]
    [InlineData("   ", "Save3")]
    [InlineData("IModelDoc2", null)]
    [InlineData("IModelDoc2", "")]
    [InlineData("IModelDoc2", "   ")]
    public void QualifiedKey_MissingPart_Throws(string? iface, string? member)
    {
        Assert.Throws<ArgumentException>(() => CallKey.QualifiedKey(iface!, member!));
    }

    [Theory]
    [InlineData("IModelDoc2.", "Save3")]
    [InlineData("IModelDoc2", "IModelDoc2.Save3")]
    public void QualifiedKey_PartCarryingTheSeparator_Throws(string iface, string member)
    {
        Assert.Throws<ArgumentException>(() => CallKey.QualifiedKey(iface, member));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void BareName_MissingKey_Throws(string? key)
    {
        Assert.Throws<ArgumentException>(() => CallKey.BareName(key!));
    }

    /// <summary>
    /// A bare key handed to a remodel write call site is a programming error: the allowlist
    /// is keyed by interface, so a bare name could never have been on it, and the call would
    /// silently take the read-only path instead.
    /// </summary>
    [Theory]
    [InlineData("Save3")]
    [InlineData("ReorderFeature")]
    [InlineData("Add3")]
    public void AssertQualified_BareKey_ThrowsNamingTheKey(string key)
    {
        ArgumentException error = Assert.Throws<ArgumentException>(() => CallKey.AssertQualified(key));
        Assert.Contains(key, error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(".Save3")]
    [InlineData("IModelDoc2.")]
    [InlineData(".")]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void AssertQualified_MalformedKey_Throws(string? key)
    {
        Assert.Throws<ArgumentException>(() => CallKey.AssertQualified(key!));
    }

    [Fact]
    public void AssertQualified_QualifiedKey_ReturnsItTrimmed()
    {
        Assert.Equal("IModelDoc2.Save3", CallKey.AssertQualified("  IModelDoc2.Save3 "));
    }

    [Theory]
    [InlineData(".Save3")]
    [InlineData("IModelDoc2.")]
    [InlineData("Save3")]
    public void IsQualified_MalformedOrBareKey_IsFalse(string key)
    {
        Assert.False(CallKey.IsQualified(key));
    }

    [Theory]
    [InlineData("Save3")]
    [InlineData("IModelDoc2.")]
    public void InterfaceName_UnqualifiedKey_Throws(string key)
    {
        Assert.Throws<ArgumentException>(() => CallKey.InterfaceName(key));
    }
}
