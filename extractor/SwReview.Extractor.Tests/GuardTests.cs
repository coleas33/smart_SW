using System;
using System.Runtime.InteropServices;
using SwReview.Extractor.Guard;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T022. The guard is the only thing standing between an agent-driven bridge and a
/// modified reviewed model (research R4, constitution Technical Constraints).
/// </summary>
public class ReadOnlyGuardTests
{
    [Theory]
    [InlineData("EditRebuild3")]
    [InlineData("ForceRebuild3")]
    [InlineData("Save3")]
    [InlineData("SaveAs3")]
    [InlineData("Delete2")]
    [InlineData("EditSuppress2")]
    [InlineData("EditUnsuppress2")]
    [InlineData("EditDelete")]
    [InlineData("ModifyDefinition")]
    public void Assert_DeniedMember_Throws(string member)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
        Assert.Equal(member, error.MemberName);
        Assert.Contains(member, error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("FeatureCut4")]
    [InlineData("FeatureCutThin")]
    [InlineData("FeatureExtrusion3")]
    [InlineData("FeatureExtrusionThin2")]
    [InlineData("InsertFeature")]
    [InlineData("InsertFeatureChamfer")]
    [InlineData("SetSystemValue")]
    [InlineData("SetSystemValues")]
    public void Assert_DeniedFamilyPrefix_Throws(string member)
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
    }

    [Theory]
    [InlineData("GetPersistReference3")]
    [InlineData("GetObjectByPersistReference3")]
    [InlineData("GetChildren")]
    [InlineData("GetSuppression2")]
    [InlineData("GetAll3")]
    [InlineData("InterferenceDetectionManager")]
    [InlineData("ViewZoomToSelection")]
    [InlineData("SelectByID2")]
    [InlineData("SaveBMP")]
    public void Assert_AllowedMember_Passes(string member)
    {
        ReadOnlyGuard.Assert(member);
    }

    [Fact]
    public void Assert_IsCaseInsensitive()
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert("save3"));
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert("FEATURECUT4"));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void Assert_MissingMemberName_Throws(string? member)
    {
        Assert.Throws<ArgumentException>(() => ReadOnlyGuard.Assert(member!));
    }

    [Theory]
    [InlineData(@"C:\runs\captures\cmp-0012.png")]
    [InlineData(@"C:\runs\captures\cmp-0012.PNG")]
    [InlineData(@"C:\runs\captures\view.bmp")]
    [InlineData(@"C:\runs\captures\view.jpg")]
    public void AssertSaveAs_ImageExtension_Passes(string path)
    {
        ReadOnlyGuard.AssertSaveAs(path);
    }

    [Theory]
    [InlineData(@"C:\vault\bracket.sldprt")]
    [InlineData(@"C:\vault\bracket.SLDASM")]
    [InlineData(@"C:\vault\bracket.slddrw")]
    [InlineData(@"C:\vault\bracket.step")]
    [InlineData(@"C:\vault\bracket")]
    public void AssertSaveAs_ModelExtension_Throws(string path)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.AssertSaveAs(path));
        Assert.Equal("SaveAs3", error.MemberName);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void AssertSaveAs_MissingPath_Throws(string? path)
    {
        Assert.Throws<ArgumentException>(() => ReadOnlyGuard.AssertSaveAs(path!));
    }
}

/// <summary>
/// T022. Three consecutive COM failures stop the bridge; the review then reports failed
/// coverage instead of retrying into a hung SOLIDWORKS session (research R4).
/// </summary>
public class CircuitBreakerTests
{
    private static COMException ComFailure() => new COMException("RPC_E_DISCONNECTED");

    [Fact]
    public void Execute_Success_ReturnsValueAndKeepsCircuitClosed()
    {
        var breaker = new CircuitBreaker();

        int result = breaker.Execute(() => 42);

        Assert.Equal(42, result);
        Assert.False(breaker.IsOpen);
        Assert.Equal(0, breaker.ConsecutiveFailures);
    }

    [Fact]
    public void Execute_TwoFailures_KeepsCircuitClosed()
    {
        var breaker = new CircuitBreaker();

        Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));
        Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));

        Assert.False(breaker.IsOpen);
        Assert.Equal(2, breaker.ConsecutiveFailures);
    }

    [Fact]
    public void Execute_ThirdFailure_OpensCircuitAndStillReportsTheOriginalError()
    {
        var breaker = new CircuitBreaker();

        Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));
        Assert.Throws<InvalidOperationException>(
            () => breaker.Execute<int>(() => throw new InvalidOperationException("stale pointer")));
        Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));

        Assert.True(breaker.IsOpen);
        Assert.Equal(3, breaker.ConsecutiveFailures);
    }

    [Fact]
    public void Execute_WhenOpen_ThrowsCircuitOpenErrorWithoutCallingTheOperation()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 3);

        bool called = false;
        Assert.Throws<CircuitOpenError>(() => breaker.Execute(() =>
        {
            called = true;
            return 1;
        }));

        Assert.False(called);
    }

    [Fact]
    public void Execute_WhenOpen_StaysOpenForFurtherCalls()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 3);

        Assert.Throws<CircuitOpenError>(() => breaker.Execute(() => 1));
        Assert.Throws<CircuitOpenError>(() => breaker.Execute(() => 2));
        Assert.True(breaker.IsOpen);
    }

    [Fact]
    public void Reset_ClosesTheCircuitAndClearsTheCount()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 3);

        breaker.Reset();

        Assert.False(breaker.IsOpen);
        Assert.Equal(0, breaker.ConsecutiveFailures);
        Assert.Equal(7, breaker.Execute(() => 7));
    }

    [Fact]
    public void Execute_SuccessAfterFailures_ClearsTheCount()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 2);

        Assert.Equal(1, breaker.Execute(() => 1));
        Assert.Equal(0, breaker.ConsecutiveFailures);

        FailTimes(breaker, 2);
        Assert.False(breaker.IsOpen);
    }

    [Fact]
    public void Execute_UnexpectedExceptionType_PropagatesWithoutCountingAsAComFailure()
    {
        var breaker = new CircuitBreaker();

        Assert.Throws<ArgumentOutOfRangeException>(
            () => breaker.Execute<int>(() => throw new ArgumentOutOfRangeException("id")));

        Assert.Equal(0, breaker.ConsecutiveFailures);
        Assert.False(breaker.IsOpen);
    }

    [Fact]
    public void Execute_NullOperation_Throws()
    {
        var breaker = new CircuitBreaker();

        Assert.Throws<ArgumentNullException>(() => breaker.Execute<int>(null!));
    }

    private static void FailTimes(CircuitBreaker breaker, int times)
    {
        for (int i = 0; i < times; i++)
        {
            Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));
        }
    }
}
