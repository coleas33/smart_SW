using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T048. A dump that stops at the first unreadable feature is worthless on a real assembly,
/// and a dump that swallows failures is worse than worthless (Principle I). Every failed
/// step becomes a Gap and the traversal keeps going.
/// </summary>
public class GapCollectorTests
{
    [Fact]
    public void Add_RecordsEveryField()
    {
        var gaps = new GapCollector();

        gaps.Add(GapKind.NotExtracted, "hole", "hol:0003", "GetDefinition returned null", null);

        Gap gap = Assert.Single(gaps.Gaps);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Equal("hole", gap.EntityKind);
        Assert.Equal("hol:0003", gap.EntityId);
        Assert.Equal("GetDefinition returned null", gap.Reason);
        Assert.Null(gap.Error);
    }

    [Fact]
    public void Add_AllowsANullEntityId()
    {
        var gaps = new GapCollector();

        gaps.Add(GapKind.Unsupported, "manifest", null, "EPDM vault version is not read by this build", null);

        Assert.Null(Assert.Single(gaps.Gaps).EntityId);
    }

    [Fact]
    public void TryStep_FailingStep_RecordsAToolErrorGapAndContinues()
    {
        var gaps = new GapCollector();

        bool ok = gaps.TryStep("component", "cmp:0004", "read the component transform",
            () => throw new InvalidOperationException("Transform2 was null"));

        Assert.False(ok);
        Gap gap = Assert.Single(gaps.Gaps);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Equal("component", gap.EntityKind);
        Assert.Equal("cmp:0004", gap.EntityId);
        Assert.Equal("read the component transform", gap.Reason);
        Assert.Contains("Transform2 was null", gap.Error!, StringComparison.Ordinal);
        Assert.Contains("InvalidOperationException", gap.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void TryStep_SucceedingStep_RecordsNothing()
    {
        var gaps = new GapCollector();
        bool ran = false;

        bool ok = gaps.TryStep("component", "cmp:0001", "read the transform", () => ran = true);

        Assert.True(ok);
        Assert.True(ran);
        Assert.Empty(gaps.Gaps);
    }

    [Fact]
    public void TryStep_ComFailure_IsRecordedLikeAnyOtherFailure()
    {
        var gaps = new GapCollector();

        Assert.False(gaps.TryStep("face", "fac:0009", "read CylinderParams",
            () => throw new COMException("RPC_E_DISCONNECTED", unchecked((int)0x80010108))));

        Assert.Contains("RPC_E_DISCONNECTED", Assert.Single(gaps.Gaps).Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void TryStep_ManyFailures_KeepsEveryGapInOrderAndTheDumpFinishes()
    {
        var gaps = new GapCollector();
        var reached = new List<string>();

        foreach (string id in new[] { "cmp:0001", "cmp:0002", "cmp:0003" })
        {
            string captured = id;
            gaps.TryStep("component", captured, "read the transform",
                () => throw new InvalidOperationException("boom " + captured));
            reached.Add(captured);
        }

        Assert.Equal(new[] { "cmp:0001", "cmp:0002", "cmp:0003" }, reached);
        Assert.Equal(new[] { "cmp:0001", "cmp:0002", "cmp:0003" }, gaps.Gaps.Select(g => g.EntityId));
        Assert.All(gaps.Gaps, g => Assert.Equal(GapKind.ToolError, g.Kind));
    }

    [Fact]
    public void TryStep_WithResult_ReturnsTheValueOnSuccess()
    {
        var gaps = new GapCollector();

        string? value = gaps.TryStep("document", "doc:abc", "read custom properties", () => "Rev B");

        Assert.Equal("Rev B", value);
        Assert.Empty(gaps.Gaps);
    }

    [Fact]
    public void TryStep_WithResult_ReturnsNullAndRecordsOnFailure()
    {
        var gaps = new GapCollector();

        string? value = gaps.TryStep<string>("document", "doc:abc", "read custom properties",
            () => throw new InvalidOperationException("GetAll3 failed"));

        Assert.Null(value);
        Assert.Equal(GapKind.ToolError, Assert.Single(gaps.Gaps).Kind);
    }

    [Fact]
    public void TryStep_CircuitOpen_PropagatesInsteadOfBeingSwallowed()
    {
        // The breaker opening means the session is gone. Recording one gap per remaining
        // entity would bury the real cause; the caller aborts the phase instead.
        var gaps = new GapCollector();

        Assert.Throws<CircuitOpenError>(() =>
            gaps.TryStep("component", "cmp:0002", "read the transform",
                () => throw new CircuitOpenError("circuit open")));

        Assert.Empty(gaps.Gaps);
    }

    [Fact]
    public void TryStep_MutatingCall_PropagatesBecauseItIsOurBug()
    {
        var gaps = new GapCollector();

        Assert.Throws<MutatingCallError>(() =>
            gaps.TryStep("component", "cmp:0002", "read the transform",
                () => ReadOnlyGuard.Assert("EditRebuild3")));

        Assert.Empty(gaps.Gaps);
    }

    [Fact]
    public void Record_TurnsAnExceptionIntoAGapWithoutRunningAnything()
    {
        var gaps = new GapCollector();

        gaps.Record("mate", "mat:0002", "read the mate entities", new NotSupportedException("weird mate"));

        Gap gap = Assert.Single(gaps.Gaps);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains("weird mate", gap.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void AddRange_MergesAnotherCollectorsGapsInOrder()
    {
        var first = new GapCollector();
        first.Add(GapKind.NotExtracted, "hole", "hol:0001", "no definition", null);

        var second = new GapCollector();
        second.Add(GapKind.Unsupported, "face", "fac:0001", "spline face", null);

        first.AddRange(second.Gaps);

        Assert.Equal(new[] { "hol:0001", "fac:0001" }, first.Gaps.Select(g => g.EntityId));
    }

    [Fact]
    public void Gaps_AreASnapshotTheCallerCannotMutate()
    {
        var gaps = new GapCollector();
        gaps.Add(GapKind.NotExtracted, "hole", null, "no definition", null);

        IReadOnlyList<Gap> first = gaps.Gaps;
        gaps.Add(GapKind.NotExtracted, "hole", null, "another", null);

        Assert.Single(first);
        Assert.Equal(2, gaps.Gaps.Count);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    public void Add_MissingEntityKind_Throws(string? entityKind)
    {
        var gaps = new GapCollector();

        Assert.Throws<ArgumentException>(() =>
            gaps.Add(GapKind.NotExtracted, entityKind!, null, "reason", null));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    public void Add_MissingReason_Throws(string? reason)
    {
        var gaps = new GapCollector();

        Assert.Throws<ArgumentException>(() =>
            gaps.Add(GapKind.NotExtracted, "hole", null, reason!, null));
    }

    [Fact]
    public void TryStep_NullStep_Throws()
    {
        var gaps = new GapCollector();

        Assert.Throws<ArgumentNullException>(() => gaps.TryStep("hole", null, "reason", (Action)null!));
    }

    /// <summary>
    /// The collector is the one object all three GetTypeName2 read sites already hold, so
    /// it carries the census and every dumper censuses into the same one.
    /// </summary>
    [Fact]
    public void TypeNames_IsOneCensusEveryHolderOfTheCollectorSharesAndStartsEmpty()
    {
        var gaps = new GapCollector();

        Assert.Empty(gaps.TypeNames.Unconsumed());

        gaps.TypeNames.AddPass(
            @"C:\vault\housing.SLDPRT", new[] { new TypeNameSighting("CutExtrude", false) });

        Assert.Equal("CutExtrude x1", Assert.Single(gaps.TypeNames.Unconsumed()).Describe());

        // A censused type name is not itself a gap; PackageWriter turns the census into one.
        Assert.Empty(gaps.Gaps);
    }
}
