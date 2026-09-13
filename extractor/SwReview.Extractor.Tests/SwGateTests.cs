using System;
using System.Runtime.InteropServices;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// The one door every interop call goes through: the read-only guard names the member
/// before it runs, the circuit breaker counts failures. Testable without SOLIDWORKS
/// because the call itself is a delegate.
/// </summary>
public class SwGateTests
{
    [Fact]
    public void Call_AllowedMember_RunsAndReturnsTheValue()
    {
        var gate = new SwGate();

        Assert.Equal(7, gate.Call("GetChildren", () => 7));
    }

    [Fact]
    public void Call_DeniedMember_ThrowsBeforeRunningTheCall()
    {
        var gate = new SwGate();
        bool ran = false;

        Assert.Throws<MutatingCallError>(() => gate.Call<int>("EditRebuild3", () => { ran = true; return 1; }));
        Assert.False(ran);
    }

    [Fact]
    public void Call_DeniedMember_DoesNotCountAsAComFailure()
    {
        var breaker = new CircuitBreaker();
        var gate = new SwGate(breaker);

        for (int i = 0; i < 5; i++)
        {
            Assert.Throws<MutatingCallError>(() => gate.Call("Save3", () => { }));
        }

        Assert.False(breaker.IsOpen);
    }

    [Fact]
    public void Call_ComFailures_OpenTheCircuitAfterThree()
    {
        var breaker = new CircuitBreaker();
        var gate = new SwGate(breaker);

        for (int i = 0; i < 3; i++)
        {
            Assert.Throws<COMException>(() => gate.Call<int>("GetChildren", () => throw new COMException("dead")));
        }

        Assert.True(breaker.IsOpen);
        Assert.Throws<CircuitOpenError>(() => gate.Call("GetChildren", () => 1));
    }

    [Fact]
    public void Call_VoidOverload_RunsTheAction()
    {
        var gate = new SwGate();
        bool ran = false;

        gate.Call("ViewZoomToSelection", () => ran = true);

        Assert.True(ran);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    public void Call_MissingMemberName_Throws(string? member)
    {
        var gate = new SwGate();

        Assert.Throws<ArgumentException>(() => gate.Call(member!, () => 1));
    }

    [Fact]
    public void Call_NullCall_Throws()
    {
        var gate = new SwGate();

        Assert.Throws<ArgumentNullException>(() => gate.Call<object>("GetChildren", null!));
    }

    [Fact]
    public void Breaker_IsTheOneTheGateWasGiven()
    {
        var breaker = new CircuitBreaker();

        Assert.Same(breaker, new SwGate(breaker).Breaker);
    }
}
