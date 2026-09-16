using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T006. Pins <see cref="SuppressionAnswer.FirstFlag"/>, the only decision on the mate path
/// that turns SOLIDWORKS' answer into an engineering fact: whether a mate is suppressed.
/// The chain-depth rule includes or excludes a graph edge on that answer, so every shape
/// <c>IFeature.IsSuppressed2</c> can come back in is pinned here rather than trusted.
///
/// <c>IsSuppressed2</c> answers with a VARIANT - one flag per configuration asked about -
/// which interop surfaces as a bare bool, a bool[], or an object[] of boxed bools depending
/// on the build. Every shape that carries no flag must answer null, because the caller
/// turns null into "unsuppressed plus a mate_suppression gap" and never into a silent false.
/// </summary>
public class SuppressionAnswerTests
{
    [Fact]
    public void FirstFlag_BareBool_IsTheFlag()
    {
        Assert.True(SuppressionAnswer.FirstFlag(true));
        Assert.False(SuppressionAnswer.FirstFlag(false));
    }

    [Fact]
    public void FirstFlag_BoolArray_IsItsFirstElement()
    {
        Assert.True(SuppressionAnswer.FirstFlag(new[] { true }));
        Assert.False(SuppressionAnswer.FirstFlag(new[] { false }));
    }

    [Fact]
    public void FirstFlag_BoolArrayOfManyConfigurations_TakesTheFirstOnly()
    {
        // swThisConfiguration was asked for, so the first flag is the configuration being
        // dumped; a longer answer must not be read from the wrong end.
        Assert.False(SuppressionAnswer.FirstFlag(new[] { false, true }));
        Assert.True(SuppressionAnswer.FirstFlag(new[] { true, false }));
    }

    [Fact]
    public void FirstFlag_BoxedBoolInObjectArray_IsUnwrapped()
    {
        Assert.True(SuppressionAnswer.FirstFlag(new object[] { true }));
        Assert.False(SuppressionAnswer.FirstFlag(new object[] { false, true }));
    }

    [Fact]
    public void FirstFlag_EmptyArray_IsNull()
    {
        Assert.Null(SuppressionAnswer.FirstFlag(new bool[0]));
        Assert.Null(SuppressionAnswer.FirstFlag(new object[0]));
    }

    [Fact]
    public void FirstFlag_ArrayWhoseFirstElementIsNotABool_IsNull()
    {
        Assert.Null(SuppressionAnswer.FirstFlag(new object[] { "x" }));
        Assert.Null(SuppressionAnswer.FirstFlag(new object?[] { null, true }));
    }

    [Fact]
    public void FirstFlag_NonBoolAnswer_IsNull()
    {
        Assert.Null(SuppressionAnswer.FirstFlag("x"));
        Assert.Null(SuppressionAnswer.FirstFlag(1));
    }

    [Fact]
    public void FirstFlag_Null_IsNull()
    {
        Assert.Null(SuppressionAnswer.FirstFlag(null));
    }
}
