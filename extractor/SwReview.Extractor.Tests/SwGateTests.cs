using System;
using System.Collections.Generic;
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

    /// <summary>
    /// T048. The suppress-test is the only mutation path in the product, and it builds its
    /// own gate. Every gate built without naming a guard - the add-in's tool service, the
    /// bridge's session, <c>SwSession.Attach</c>'s fallback, every dumper - is read-only and
    /// refuses the two members that test is exempted from.
    /// </summary>
    [Theory]
    [InlineData("ForceRebuild3")]
    [InlineData("SetSuppression2")]
    public void Call_GateBuiltWithoutAGuard_RefusesTheSuppressTestMembers(string member)
    {
        var parameterless = new SwGate();
        var withBreaker = new SwGate(new CircuitBreaker());
        bool ran = false;

        Assert.Throws<MutatingCallError>(() => parameterless.Call<int>(member, () => { ran = true; return 1; }));
        Assert.Throws<MutatingCallError>(() => withBreaker.Call(member, () => ran = true));
        Assert.False(ran);
    }

    [Fact]
    public void Call_CustomGuard_IsConsultedInsteadOfTheReadOnlyGuard()
    {
        var guard = new FakeGuard(denied: "GetChildren");
        var gate = new SwGate(new CircuitBreaker(), guard);

        // The read-only guard would refuse this one and allow the other; the fake decides.
        Assert.Equal(7, gate.Call("ForceRebuild3", () => 7));
        Assert.Throws<MutatingCallError>(() => gate.Call<int>("GetChildren", () => 1));

        Assert.Equal(new[] { "ForceRebuild3", "GetChildren" }, guard.Asked);
    }

    [Fact]
    public void Call_CustomGuard_StillReportsToTheObserver()
    {
        var observer = new RecordingObserver();
        var gate = new SwGate(new CircuitBreaker(), new FakeGuard(denied: "GetChildren"))
        {
            Observer = observer,
        };

        gate.Call("ForceRebuild3", () => 1);
        Assert.Throws<MutatingCallError>(() => gate.Call<int>("GetChildren", () => 1));

        Assert.Equal(new[] { "ForceRebuild3", "GetChildren" }, observer.Gated);
        Assert.Equal("GetChildren", Assert.Single(observer.Refusals).MemberName);
    }

    [Fact]
    public void Call_CustomGuard_StillCountsComFailuresAgainstTheBreaker()
    {
        var breaker = new CircuitBreaker();
        var gate = new SwGate(breaker, new FakeGuard(denied: "GetChildren"));

        Assert.Throws<MutatingCallError>(() => gate.Call<int>("GetChildren", () => 1));
        Assert.False(breaker.IsOpen);
        Assert.Equal(0, breaker.ConsecutiveFailures);

        for (int i = 0; i < 3; i++)
        {
            Assert.Throws<COMException>(() => gate.Call<int>("ForceRebuild3", () => throw new COMException("dead")));
        }

        Assert.True(breaker.IsOpen);
    }

    /// <summary>
    /// T048/T055. The guard-only door. <c>SwSuppressTarget</c> makes its two mutating interop
    /// calls itself, the way <c>SwFeatureReader</c> does, so it asks the gate about the member
    /// at the call site rather than trusting its caller to have asked: a mutating member must
    /// not be reachable with the guard never consulted.
    /// </summary>
    [Theory]
    [InlineData("ForceRebuild3")]
    [InlineData("SetSuppression2")]
    public void Assert_GateBuiltWithoutAGuard_RefusesTheSuppressTestMembers(string member)
    {
        Assert.Throws<MutatingCallError>(() => new SwGate().Assert(member));
        Assert.Throws<MutatingCallError>(() => new SwGate(new CircuitBreaker()).Assert(member));
    }

    [Fact]
    public void Assert_AllowedMember_Passes()
    {
        new SwGate().Assert("GetChildren");
    }

    [Fact]
    public void Assert_SuppressTestGuard_AllowsExactlyTheTwoExemptMembers()
    {
        var gate = new SwGate(new CircuitBreaker(), new SuppressTestGuard());

        gate.Assert("SetSuppression2");
        gate.Assert("ForceRebuild3");
        Assert.Throws<MutatingCallError>(() => gate.Assert("ForceRebuildAll"));
    }

    [Fact]
    public void Assert_DeniedMember_TellsTheObserverAndLeavesTheBreakerClosed()
    {
        // Same guard and same observer as Call, and no breaker: the call that follows an
        // Assert is counted by the Call that wraps it, and a guard decision is not a sick
        // SOLIDWORKS session.
        var observer = new RecordingObserver();
        var breaker = new CircuitBreaker();
        var gate = new SwGate(breaker, new FakeGuard(denied: "GetChildren")) { Observer = observer };

        gate.Assert("ForceRebuild3");
        Assert.Throws<MutatingCallError>(() => gate.Assert("GetChildren"));

        Assert.Equal(new[] { "ForceRebuild3", "GetChildren" }, observer.Gated);
        Assert.Equal("GetChildren", Assert.Single(observer.Refusals).MemberName);
        Assert.False(breaker.IsOpen);
        Assert.Equal(0, breaker.ConsecutiveFailures);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    public void Assert_MissingMemberName_Throws(string? member)
    {
        Assert.Throws<ArgumentException>(() => new SwGate().Assert(member!));
    }

    /// <summary>A guard that answers from one denied name, so the fake and the read-only
    /// guard disagree about every member the tests use.</summary>
    private sealed class FakeGuard : ICallGuard
    {
        private readonly string _denied;

        public FakeGuard(string denied) => _denied = denied;

        public List<string> Asked { get; } = new List<string>();

        public void Assert(string interopMember)
        {
            Asked.Add(interopMember);
            if (string.Equals(interopMember, _denied, StringComparison.Ordinal))
            {
                throw new MutatingCallError(interopMember, $"{interopMember} is refused by the test guard.");
            }
        }
    }

    private sealed class RecordingObserver : ISwGateObserver
    {
        public List<string> Gated { get; } = new List<string>();

        public List<MutatingCallError> Refusals { get; } = new List<MutatingCallError>();

        void ISwGateObserver.Gated(string interopMember) => Gated.Add(interopMember);

        public void Refused(MutatingCallError refusal) => Refusals.Add(refusal);
    }
}
