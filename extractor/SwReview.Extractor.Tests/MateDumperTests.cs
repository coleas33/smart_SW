using System;
using System.Linq;
using System.Reflection;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T035. <c>MateEntity.resolution_status</c>, the one schema 1.4.0 field the <c>mate</c> phase
/// writes (<c>contracts/ir-additions.md</c> section 1).
///
/// It costs <b>no new interop call</b>. <c>MateDumper.ReadEntities</c> already reads
/// <c>IMateEntity2.Reference</c>; what it could not do was tell a reference that came back
/// null from a read that threw, because both produce a null <c>persist_ref</c>. That
/// conflation is the whole defect <c>standards.assembly.mate_references</c> hunts: a mate
/// pointing at an entity that is gone looks exactly like a mate the dump could not read, and
/// one of those is a finding while the other is unresolved coverage.
///
/// The read is pinned through the dumper's gated helper rather than through <c>Dump</c>,
/// because the dumper holds a live <c>IMate2</c> and this machine has no SOLIDWORKS seat.
/// </summary>
public class MateDumperTests
{
    private const string MateId = "mat:0003";
    private const string FeatureName = "Concentric7";

    private readonly GapCollector _gaps = new GapCollector();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();

    public MateDumperTests()
    {
        _gate.Observer = _observer;
    }

    [Fact]
    public void ReadEntityReference_NonNull_IsResolvedAndCarriesTheReference()
    {
        var entity = new object();

        MateEntityReferenceRead read = MateDumper.ReadEntityReference(
            MateId, FeatureName, 0, _gaps, _gate, () => entity);

        Assert.Equal(MateEntityResolution.Resolved, read.Status);
        Assert.Same(entity, read.Reference);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadEntityReference_Null_IsUnresolvedAndIsNotAGap()
    {
        // A mate whose entity is gone is a FINDING, not missing evidence: the dump read the
        // reference successfully and SOLIDWORKS answered "nothing".
        MateEntityReferenceRead read = MateDumper.ReadEntityReference(
            MateId, FeatureName, 1, _gaps, _gate, () => null);

        Assert.Equal(MateEntityResolution.Unresolved, read.Status);
        Assert.Null(read.Reference);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadEntityReference_ThatThrew_IsUnknownPlusAMateEntityReferenceGap()
    {
        MateEntityReferenceRead read = MateDumper.ReadEntityReference(
            MateId,
            FeatureName,
            2,
            _gaps,
            _gate,
            () => throw new InvalidOperationException("the mate entity did not answer"));

        Assert.Equal(MateEntityResolution.Unknown, read.Status);
        Assert.Null(read.Reference);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("mate_entity_reference", gap.EntityKind);
        Assert.Equal(MateId, gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(FeatureName, gap.Reason, StringComparison.Ordinal);
        Assert.Contains("the mate entity did not answer", gap.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void ReadEntityReference_AsksForNoMemberTheDumpDidNotAlreadyRead()
    {
        MateDumper.ReadEntityReference(MateId, FeatureName, 0, _gaps, _gate, () => new object());

        // The member name is the one MateDumper already put through the gate before 1.4.0.
        // A new member here would be a new interop call to answer a question the existing
        // read already answers.
        Assert.Equal(new[] { "MateEntity.Reference" }, _observer.Members);
    }

    [Fact]
    public void ReadEntityReference_NamesTheEntityIndexSoTwoFailuresOnOneMateAreTwoRows()
    {
        MateDumper.ReadEntityReference(
            MateId, FeatureName, 0, _gaps, _gate, () => throw new InvalidOperationException("a"));
        MateDumper.ReadEntityReference(
            MateId, FeatureName, 1, _gaps, _gate, () => throw new InvalidOperationException("b"));

        Assert.Equal(2, _gaps.Count);
        Assert.NotEqual(_gaps.Gaps[0].Reason, _gaps.Gaps[1].Reason);
    }

    [Fact]
    public void ResolutionStatus_IsNullOnAnEntityNobodyRead()
    {
        // Null means "written before 1.4.0", which is a third thing again: the package is old,
        // not the mate broken. It is omitted when null, so an older package is unchanged.
        Assert.Null(new MateEntityRef().ResolutionStatus);
    }

    [Fact]
    public void Dump_OffersNoWayToWalkASubAssemblysMateGroup()
    {
        // Difference h. The dumper walks the ROOT assembly's mate group and no other, which is
        // a data gap the Python side must name rather than a defect it may hide: a
        // sub-assembly's own mates are simply not in the package, so
        // standards.assembly.mate_references reports unresolved once per sub-assembly instead
        // of passing it. Nothing here can walk a second document even if a caller wanted it
        // to - Dump(DumpScope) is the only entry point, and it takes no document.
        MethodInfo[] entries = typeof(MateDumper)
            .GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .ToArray();

        MethodInfo dump = Assert.Single(entries);
        Assert.Equal("Dump", dump.Name);
        Assert.Equal(new[] { typeof(DumpScope) }, dump.GetParameters().Select(p => p.ParameterType));
    }
}
