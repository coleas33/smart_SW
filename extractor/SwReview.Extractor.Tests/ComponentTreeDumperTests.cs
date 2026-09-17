using System;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T033. The four schema 1.4.0 reads <see cref="ComponentTreeDumper.ReadNode"/> adds to every
/// traversed instance: the appearance override, the transparency slot, the visibility state
/// and the pattern origin (<c>contracts/ir-additions.md</c> section 1).
///
/// They live inside <c>Traverse</c>, where no <c>cmp:NNNN</c> exists yet, so every failure is
/// a <see cref="GapCollector.TryStep"/> gap with a null entity id - the same shape every other
/// traversal gap has, and the reason the deferred-gap dance
/// <c>ConstrainedStatusError</c> needs is not repeated here.
///
/// The reads are pinned through the dumper's gated helpers rather than through
/// <c>Traverse</c>, because the traversal holds a live <c>IComponent2</c> and this machine has
/// no SOLIDWORKS seat. Each helper owns the policy: which read is worth making at all, what
/// becomes a gap, and what is recorded when the answer is unknown. The interop expression
/// (<c>component.Visible</c>, <c>component.GetMaterialPropertyValues2(1, null)</c>) stays at
/// the call site.
///
/// Two of the four are here because the macro got them wrong:
///
///   * <b>The transparency slot replaces a -1 sentinel</b> that conflated "no appearance
///     override" with a real value, so <c>has_appearance_override</c> is read first and the
///     slot is only asked for when there is something to read.
///   * <b><c>IsHidden(bool)</c> is never called.</b> With ConsiderSuppressed it is the macro's
///     difference-c bug - a suppressed component reading as hidden - and <c>Visible</c>
///     answers the same question with one fewer conflated state (research R3.4).
/// </summary>
public class ComponentTreeDumperTests
{
    private const string Key = "sub-2/bracket-3";

    private readonly GapCollector _gaps = new GapCollector();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();

    public ComponentTreeDumperTests()
    {
        _gate.Observer = _observer;
    }

    // ---- HasMaterialPropertyValues -------------------------------------------------

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void ReadHasAppearanceOverride_RecordsTheAnswerThroughTheGate(bool answer)
    {
        bool? has = ComponentTreeDumper.ReadHasAppearanceOverride(Key, _gaps, _gate, () => answer);

        Assert.Equal(answer, has);
        Assert.Equal(new[] { "HasMaterialPropertyValues" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadHasAppearanceOverride_ThatThrew_IsNullPlusAComponentTransparencyGap()
    {
        bool? has = ComponentTreeDumper.ReadHasAppearanceOverride(
            Key, _gaps, _gate, () => throw new InvalidOperationException("no answer"));

        Assert.Null(has);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_transparency", gap.EntityKind);

        // Inside Traverse: no cmp:NNNN exists yet, so the gap names the component in its
        // reason and carries no entity id, exactly as every other traversal gap does.
        Assert.Null(gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
        Assert.Contains("no answer", gap.Error!, StringComparison.Ordinal);
    }

    // ---- GetMaterialPropertyValues2 slot 7 -----------------------------------------

    [Fact]
    public void ReadTransparency_RecordsSlotSevenVerbatim()
    {
        // Verbatim: the extractor does not decide which number means transparent. Which it is
        // - and whether slot 7 is the slot on this build - is PROBE-2, and until it answers
        // the Python constant TRANSPARENCY_POLARITY leaves the check unresolved.
        var values = new double[] { 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 0.9 };

        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: true, key: Key, gaps: _gaps, gate: _gate, read: () => values);

        Assert.Equal(0.85, transparency);
        Assert.Equal(new[] { "GetMaterialPropertyValues2" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadTransparency_ReadsSlotSevenOutOfABoxedVariantArrayToo()
    {
        object[] values = { 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.25, 0.9 };

        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: true, key: Key, gaps: _gaps, gate: _gate, read: () => values);

        Assert.Equal(0.25, transparency);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadTransparency_WithNoAppearanceOverride_IsNullWithoutAGapAndWithoutTheCall()
    {
        // There is nothing to read, so the null is not a gap: a coverage row on every
        // component of every assembly would bury the components that really could not be read
        // (contracts/ir-additions.md section 1).
        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: false,
            key: Key,
            gaps: _gaps,
            gate: _gate,
            read: () => throw new InvalidOperationException("there is nothing to read"));

        Assert.Null(transparency);
        Assert.Empty(_gaps.Gaps);
        Assert.Empty(_observer.Members);
    }

    [Fact]
    public void ReadTransparency_WhenTheOverrideItselfWasUnreadable_AddsNoSecondGap()
    {
        // has_appearance_override null means ReadHasAppearanceOverride already wrote the gap.
        // Asking anyway would record the same failure twice in the coverage report.
        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: null,
            key: Key,
            gaps: _gaps,
            gate: _gate,
            read: () => throw new InvalidOperationException("never called"));

        Assert.Null(transparency);
        Assert.Empty(_gaps.Gaps);
        Assert.Empty(_observer.Members);
    }

    [Fact]
    public void ReadTransparency_ThatThrew_IsNullPlusAComponentTransparencyGap()
    {
        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: true,
            key: Key,
            gaps: _gaps,
            gate: _gate,
            read: () => throw new InvalidOperationException("the appearance did not answer"));

        Assert.Null(transparency);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_transparency", gap.EntityKind);
        Assert.Null(gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(null)]
    [InlineData(4)]
    public void ReadTransparency_WithNoSlotSeven_IsNullPlusAComponentTransparencyGap(int? length)
    {
        // An answer that is not a nine-slot array is an answer nobody can read slot 7 out of.
        // Unknown stays unknown: it is a gap, never a zero.
        object? answer = length == null ? null : new double[length.Value];

        double? transparency = ComponentTreeDumper.ReadTransparency(
            hasOverride: true, key: Key, gaps: _gaps, gate: _gate, read: () => answer);

        Assert.Null(transparency);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_transparency", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
    }

    // ---- Visible -------------------------------------------------------------------

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(-1)]
    public void ReadVisibility_RecordsTheStateVerbatim(int state)
    {
        // swComponentVisibilityState_e: hidden 0, visible 1, unknown -1. The extractor records
        // the number and Python names it (plan Structure Decision 1).
        int? visibility = ComponentTreeDumper.ReadVisibility(Key, _gaps, _gate, () => state);

        Assert.Equal(state, visibility);
        Assert.Equal(new[] { "Visible" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadVisibility_NeverAsksIsHidden()
    {
        ComponentTreeDumper.ReadVisibility(Key, _gaps, _gate, () => 1);

        // research R3.4: with ConsiderSuppressed = true IsHidden is the macro's difference-c
        // bug, and with false it answers the same question with one fewer state.
        Assert.DoesNotContain("IsHidden", _observer.Members);
    }

    [Fact]
    public void ReadVisibility_ThatThrew_IsNullPlusAComponentVisibilityGap()
    {
        int? visibility = ComponentTreeDumper.ReadVisibility(
            Key, _gaps, _gate, () => throw new InvalidOperationException("no answer"));

        Assert.Null(visibility);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_visibility", gap.EntityKind);
        Assert.Null(gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
    }

    // ---- IsPatternInstance ---------------------------------------------------------

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void ReadIsPatternInstance_RecordsTheAnswerThroughTheGate(bool answer)
    {
        bool? pattern = ComponentTreeDumper.ReadIsPatternInstance(Key, _gaps, _gate, () => answer);

        Assert.Equal(answer, pattern);
        Assert.Equal(new[] { "IsPatternInstance" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadIsPatternInstance_ThatThrew_IsNullPlusAComponentPatternGap()
    {
        bool? pattern = ComponentTreeDumper.ReadIsPatternInstance(
            Key, _gaps, _gate, () => throw new InvalidOperationException("no answer"));

        Assert.Null(pattern);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("component_pattern", gap.EntityKind);
        Assert.Null(gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(Key, gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void PatternId_AndIsPatternInstance_AreTwoFactsNotOne()
    {
        // pattern_id keeps the pattern's NAME for the reason text and cannot replace the
        // flag: a null pattern_id conflates "not in a pattern" with "the pattern map was
        // never built" (contracts/ir-additions.md section 1). The node carries both, and one
        // does not default the other.
        var node = new ComponentNode
        {
            Key = Key,
            PatternId = "LocalLPattern1",
            IsPatternInstance = ComponentTreeDumper.ReadIsPatternInstance(
                Key, _gaps, _gate, () => throw new InvalidOperationException("no answer")),
        };

        Assert.Equal("LocalLPattern1", node.PatternId);
        Assert.Null(node.IsPatternInstance);
    }

    // ---- the four fields travel on the node ----------------------------------------

    [Fact]
    public void TheFourFields_DefaultToUnknownOnANodeNobodyRead()
    {
        // Null, not false and not zero: a node built by a caller that never asked carries no
        // answer, and PackageWriter copies exactly that onto the instance.
        var node = new ComponentNode();

        Assert.Null(node.HasAppearanceOverride);
        Assert.Null(node.TransparencyRaw);
        Assert.Null(node.VisibilityRaw);
        Assert.Null(node.IsPatternInstance);
    }
}
