using System;
using System.Runtime.InteropServices;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T031. The four schema 1.4.0 reads <see cref="PropertyDumper"/> adds to the
/// <c>document</c> phase: the exploded state, the what's-wrong count, the mass override and
/// the configuration the material was read in
/// (<c>contracts/ir-additions.md</c> section 1).
///
/// The reads are pinned through the dumper's own gated helpers rather than through
/// <c>Dump</c>, because <see cref="PropertyDumper"/> holds an <c>ISldWorks</c> and an
/// <c>IModelDoc2</c> and this machine has no SOLIDWORKS seat - the same split
/// <see cref="FeatureDumper"/> makes with <see cref="IFeatureReader"/>, except that here the
/// seam is one delegate per read instead of a whole interface, because four reads do not
/// earn one. Each helper owns the policy that matters: which documents the question applies
/// to, what becomes a gap, and what is recorded when the answer is unknown. The interop
/// expression itself (<c>model.IsExploded()</c>, <c>((IMassProperty)mp).OverrideMass</c>)
/// stays at the call site in <c>PropertyDumper.Read</c>.
///
/// Three properties matter more than the value mapping:
///
///   * <b>Nothing is defaulted.</b> A read that threw is null plus the gap entity kind
///     <c>data-model.md</c> section 2.4 names, so the rule layer reports unresolved rather
///     than passing a document whose evidence never arrived.
///   * <b>An absent question is not a gap.</b> A part has no exploded state and a drawing has
///     no material configuration; those nulls are silent, because naming them would put a
///     coverage row on every part in the package.
///   * <b>Nothing is rebuilt.</b> The what's-wrong count is read as the document stands.
/// </summary>
public class PropertyDumperTests
{
    private const string AssemblyName = "bracket-assy.SLDASM";
    private const string PartName = "housing.SLDPRT";
    private const string DocumentId = "doc:0001";

    private readonly GapCollector _gaps = new GapCollector();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();

    public PropertyDumperTests()
    {
        _gate.Observer = _observer;
    }

    // ---- IsExploded ----------------------------------------------------------------

    [Fact]
    public void ReadIsExploded_ForAnAssembly_RecordsTheAnswerThroughTheGate()
    {
        bool? exploded = PropertyDumper.ReadIsExploded(
            DocumentKind.Assembly, DocumentId, AssemblyName, _gaps, _gate, () => true);

        Assert.True(exploded);
        Assert.Contains("IsExploded", _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadIsExploded_ForAnAssemblyThatIsNotExploded_RecordsFalseNotNull()
    {
        // false and null are different answers: false is a pass, null is unresolved coverage.
        bool? exploded = PropertyDumper.ReadIsExploded(
            DocumentKind.Assembly, DocumentId, AssemblyName, _gaps, _gate, () => false);

        Assert.False(exploded);
        Assert.Empty(_gaps.Gaps);
    }

    [Theory]
    [InlineData(DocumentKind.Part)]
    [InlineData(DocumentKind.Drawing)]
    public void ReadIsExploded_ForAPartOrADrawing_IsNullWithoutAGapAndWithoutTheCall(
        DocumentKind kind)
    {
        bool? exploded = PropertyDumper.ReadIsExploded(
            kind,
            DocumentId,
            PartName,
            _gaps,
            _gate,
            () => throw new InvalidOperationException("the question does not apply"));

        Assert.Null(exploded);
        Assert.Empty(_gaps.Gaps);
        Assert.DoesNotContain("IsExploded", _observer.Members);
    }

    [Fact]
    public void ReadIsExploded_ThatThrew_IsNullPlusAnAssemblyExplodedGap()
    {
        bool? exploded = PropertyDumper.ReadIsExploded(
            DocumentKind.Assembly,
            DocumentId,
            AssemblyName,
            _gaps,
            _gate,
            () => throw new InvalidOperationException("the assembly did not answer"));

        Assert.Null(exploded);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("assembly_exploded", gap.EntityKind);
        Assert.Equal(DocumentId, gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(AssemblyName, gap.Reason, StringComparison.Ordinal);
        Assert.Contains("the assembly did not answer", gap.Error!, StringComparison.Ordinal);
    }

    // ---- GetWhatsWrongCount --------------------------------------------------------

    [Fact]
    public void ReadRebuildErrorCount_RecordsTheCountAsTheDocumentStandsAndRebuildsNothing()
    {
        int? count = PropertyDumper.ReadRebuildErrorCount(
            DocumentId, AssemblyName, _gaps, _gate, () => 3);

        Assert.Equal(3, count);
        Assert.Equal(new[] { "GetWhatsWrongCount" }, _observer.Members);

        // Difference g: the macro rebuilt the model to refresh this number. Nothing here does.
        Assert.DoesNotContain("EditRebuild3", _observer.Members);
        Assert.DoesNotContain("ForceRebuild3", _observer.Members);
        Assert.DoesNotContain("ForceRebuildAll", _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadRebuildErrorCount_OfZero_IsZeroNotNull()
    {
        Assert.Equal(0, PropertyDumper.ReadRebuildErrorCount(
            DocumentId, AssemblyName, _gaps, _gate, () => 0));
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadRebuildErrorCount_ThatThrew_IsNullPlusARebuildErrorCountGap()
    {
        int? count = PropertyDumper.ReadRebuildErrorCount(
            DocumentId,
            AssemblyName,
            _gaps,
            _gate,
            () => throw new InvalidOperationException("the extension did not answer"));

        Assert.Null(count);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("rebuild_error_count", gap.EntityKind);
        Assert.Equal(DocumentId, gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(AssemblyName, gap.Reason, StringComparison.Ordinal);
    }

    // ---- OverrideMass --------------------------------------------------------------

    [Fact]
    public void ReadMassOverridden_ReadsOffTheObjectCreateMassProperty2Returned()
    {
        // The object is the one CreateMassProperty2 already returned for the mass read, so
        // the dump makes one call, not two, and the override answer does not depend on
        // whether the model has a solid volume.
        var massProperty = new object();
        object? seen = null;

        bool? overridden = PropertyDumper.ReadMassOverridden(
            massProperty,
            DocumentId,
            PartName,
            _gaps,
            _gate,
            mp =>
            {
                seen = mp;
                return true;
            });

        Assert.True(overridden);
        Assert.Same(massProperty, seen);
        Assert.Equal(new[] { "OverrideMass" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadMassOverridden_ForASurfaceOnlyPart_StillAnswers()
    {
        // A surface-only part has no volume, so PropertyDumper.ReadMass returns null plus its
        // own gap. The override question is answered anyway, before that gate, because
        // standards.part.material_assigned would otherwise be unresolved for every one of
        // them (contracts/ir-additions.md section 1). The ordering is a property of
        // PropertyDumper.Read, which hands this helper the mass-property object it created;
        // what is pinned here is that the answer needs nothing but that object.
        bool? overridden = PropertyDumper.ReadMassOverridden(
            new object(), DocumentId, PartName, _gaps, _gate, mp => false);

        Assert.False(overridden);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadMassOverridden_WhenTheObjectIsNull_IsNullPlusAMassOverrideGap()
    {
        bool? overridden = PropertyDumper.ReadMassOverridden(
            null, DocumentId, PartName, _gaps, _gate, mp => true);

        Assert.Null(overridden);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("mass_override", gap.EntityKind);
        Assert.Equal(DocumentId, gap.EntityId);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Contains(PartName, gap.Reason, StringComparison.Ordinal);
        Assert.DoesNotContain("OverrideMass", _observer.Members);
    }

    [Fact]
    public void ReadMassOverridden_WhenTheCastFails_IsNullPlusAMassOverrideGap()
    {
        // IMassProperty2 exposes no OverrideMass and declares no base interface in this
        // interop, so the cast to IMassProperty is the UNVERIFIED half of the read
        // (research R3.2). It fails as a gap, not as a false.
        bool? overridden = PropertyDumper.ReadMassOverridden(
            new object(),
            DocumentId,
            PartName,
            _gaps,
            _gate,
            mp => throw new InvalidCastException("the mass property is not an IMassProperty"));

        Assert.Null(overridden);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("mass_override", gap.EntityKind);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains("InvalidCastException", gap.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void ReadMassOverridden_WhenTheReadThrows_IsNullPlusAMassOverrideGap()
    {
        bool? overridden = PropertyDumper.ReadMassOverridden(
            new object(),
            DocumentId,
            PartName,
            _gaps,
            _gate,
            mp => throw new InvalidOperationException("the mass property did not answer"));

        Assert.Null(overridden);
        Assert.Equal("mass_override", Assert.Single(_gaps.Gaps).EntityKind);
    }

    // ---- OverrideMass, read two ways (feature 010 T068) ----------------------------
    //
    // The one-object read above cast CreateMassProperty2's object to IMassProperty, and on
    // SOLIDWORKS 2024 that cast raised on every document of both recorded assemblies
    // (research R2.24, analyst fact 27): IMassProperty2 has no OverrideMass. The read now
    // goes through the interface that has it - IModelDocExtension.CreateMassProperty()
    // returns MassProperty, which implements IMassProperty - and falls back to
    // IMassProperty2.GetOverrideOptions(), whose IMassPropertyOverrideOptions carries an
    // OverrideMass of its own (contracts/mass-material.md section 4). Both are reflected on
    // the 2024 SP5 interop; which one answers on a seat is SC-008's question (T103).

    private readonly object _massProperty = new object();
    private readonly object _massProperty2 = new object();

    [Fact]
    public void ReadMassOverridden_TwoPaths_ReadsTheObjectCreateMassPropertyReturnsFirst()
    {
        object? seen = null;

        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => _massProperty,
            mp =>
            {
                seen = mp;
                return true;
            },
            _massProperty2,
            mp => throw new InvalidOperationException("the fallback must not be asked"),
            DocumentId,
            PartName,
            _gaps,
            _gate);

        Assert.True(overridden);
        Assert.Same(_massProperty, seen);
        Assert.Equal(new[] { "CreateMassProperty", "OverrideMass" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadMassOverridden_TwoPaths_AFalseFromTheFirstPathIsTheAnswer()
    {
        // false is an answer, not a failure: the fallback is not asked to overrule it.
        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => _massProperty,
            mp => false,
            _massProperty2,
            mp => true,
            DocumentId,
            PartName,
            _gaps,
            _gate);

        Assert.False(overridden);
        Assert.DoesNotContain("GetOverrideOptions", _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadMassOverridden_TwoPaths_WhenTheFirstReadThrows_AsksGetOverrideOptions()
    {
        object? seen = null;

        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => _massProperty,
            mp => throw new InvalidCastException("not an IMassProperty"),
            _massProperty2,
            mp =>
            {
                seen = mp;
                return true;
            },
            DocumentId,
            PartName,
            _gaps,
            _gate);

        Assert.True(overridden);

        // The fallback reads the object CreateMassProperty2 already returned for the mass
        // read, so it costs no second creation call.
        Assert.Same(_massProperty2, seen);
        Assert.Equal(
            new[] { "CreateMassProperty", "OverrideMass", "GetOverrideOptions" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadMassOverridden_TwoPaths_WhenCreateMassPropertyReturnsNothing_AsksGetOverrideOptions()
    {
        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => null,
            mp => throw new InvalidOperationException("there is no object to read"),
            _massProperty2,
            mp => false,
            DocumentId,
            PartName,
            _gaps,
            _gate);

        Assert.False(overridden);
        Assert.Equal(new[] { "CreateMassProperty", "GetOverrideOptions" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void ReadMassOverridden_TwoPaths_WhenCreateMassPropertyThrows_AsksGetOverrideOptions()
    {
        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => throw new COMException("the extension did not answer"),
            mp => true,
            _massProperty2,
            mp => true,
            DocumentId,
            PartName,
            _gaps,
            _gate);

        Assert.True(overridden);
        Assert.Equal(new[] { "CreateMassProperty", "GetOverrideOptions" }, _observer.Members);
        Assert.Empty(_gaps.Gaps);

        // The fallback's success closes the breaker again: one sick path is not a sick session.
        Assert.Equal(0, _gate.Breaker.ConsecutiveFailures);
    }

    [Fact]
    public void ReadMassOverridden_TwoPaths_WhenBothThrow_IsNullPlusOneGapNamingBothPaths()
    {
        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => _massProperty,
            mp => throw new InvalidCastException("not an IMassProperty"),
            _massProperty2,
            mp => throw new COMException("no override options"),
            DocumentId,
            PartName,
            _gaps,
            _gate);

        Assert.Null(overridden);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("mass_override", gap.EntityKind);
        Assert.Equal(DocumentId, gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains(PartName, gap.Reason, StringComparison.Ordinal);
        Assert.Contains("CreateMassProperty", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("GetOverrideOptions", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("InvalidCastException: not an IMassProperty", gap.Error!, StringComparison.Ordinal);
        Assert.Contains("COMException: no override options", gap.Error!, StringComparison.Ordinal);
        Assert.Equal(
            new[] { "CreateMassProperty", "OverrideMass", "GetOverrideOptions" }, _observer.Members);
    }

    [Fact]
    public void ReadMassOverridden_TwoPaths_WhenTheFirstThrowsAndThereIsNoSecondObject_IsNullPlusOneGap()
    {
        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => _massProperty,
            mp => throw new InvalidCastException("not an IMassProperty"),
            null,
            mp => throw new InvalidOperationException("there is no object to read"),
            DocumentId,
            PartName,
            _gaps,
            _gate);

        Assert.Null(overridden);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("mass_override", gap.EntityKind);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains("CreateMassProperty2 returned nothing", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("InvalidCastException", gap.Error!, StringComparison.Ordinal);
        Assert.DoesNotContain("GetOverrideOptions", _observer.Members);
    }

    [Fact]
    public void ReadMassOverridden_TwoPaths_WhenNeitherPathHasAnObject_IsNullPlusANotExtractedGap()
    {
        // Nothing threw, so there is no error to record: both creation calls simply answered
        // with nothing, which is "not extracted", as the one-object read has it.
        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => null,
            mp => true,
            null,
            mp => true,
            DocumentId,
            PartName,
            _gaps,
            _gate);

        Assert.Null(overridden);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal("mass_override", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Null(gap.Error);
        Assert.Contains("CreateMassProperty returned nothing", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("CreateMassProperty2 returned nothing", gap.Reason, StringComparison.Ordinal);
        Assert.Equal(new[] { "CreateMassProperty" }, _observer.Members);
    }

    [Fact]
    public void ReadMassOverridden_TwoPaths_AGuardRefusalIsNotSwallowedAsAFailedPath()
    {
        // A refused member is our bug, not a property of the model (GapCollector's rule): it
        // must surface rather than quietly fall through to the other path.
        var refusing = new SwGate(new CircuitBreaker(), new RefuseEverythingGuard());

        Assert.Throws<MutatingCallError>(() => PropertyDumper.ReadMassOverridden(
            () => _massProperty,
            mp => true,
            _massProperty2,
            mp => true,
            DocumentId,
            PartName,
            _gaps,
            refusing));
        Assert.Empty(_gaps.Gaps);
    }

    // ---- the overridden-mass gap (feature 010) -------------------------------------
    //
    // ReadMass used to decide this gap from its own GetOverrideOptions() call, testing the
    // answer with `is int[]`; the call returns an IMassPropertyOverrideOptions object, so the
    // gap its doc comment promised never fired. It is now decided from the override answer the
    // two-path read already produced, with no second call.

    private const string OverriddenMassReason =
        "The mass properties are OVERRIDDEN in SOLIDWORKS; the values recorded were typed by a "
        + "user, not computed from the geometry.";

    [Fact]
    public void RecordOverriddenMass_WhenTheMassIsOverridden_AddsExactlyOneGap()
    {
        PropertyDumper.RecordOverriddenMass(true, DocumentId, _gaps);

        Gap gap = Assert.Single(_gaps.Gaps);
        Assert.Equal(GapKind.Unsupported, gap.Kind);
        Assert.Equal("document", gap.EntityKind);
        Assert.Equal(DocumentId, gap.EntityId);
        Assert.Equal(OverriddenMassReason, gap.Reason);
        Assert.Null(gap.Error);
    }

    [Fact]
    public void RecordOverriddenMass_WhenTheMassIsNotOverridden_AddsNothing()
    {
        PropertyDumper.RecordOverriddenMass(false, DocumentId, _gaps);

        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void RecordOverriddenMass_WhenTheOverrideIsUnknown_DoesNotDuplicateTheReadsOwnGap()
    {
        // Unknown is the override read's to report, and it already has: one mass_override gap
        // naming both paths. Nothing is added beside it.
        bool? overridden = PropertyDumper.ReadMassOverridden(
            () => null,
            mp => true,
            null,
            mp => true,
            DocumentId,
            PartName,
            _gaps,
            _gate);
        Assert.Null(overridden);
        Gap readGap = Assert.Single(_gaps.Gaps);

        PropertyDumper.RecordOverriddenMass(overridden, DocumentId, _gaps);

        Assert.Same(readGap, Assert.Single(_gaps.Gaps));
        Assert.Equal("mass_override", readGap.EntityKind);
    }

    [Fact]
    public void RecordOverriddenMass_AsksSolidWorksNothing()
    {
        // The answer is the one the override read produced; a second GetOverrideOptions call is
        // exactly what used to decide this gap wrongly.
        PropertyDumper.RecordOverriddenMass(true, DocumentId, _gaps);

        Assert.Empty(_observer.Members);
    }

    private sealed class RefuseEverythingGuard : ICallGuard
    {
        public void Assert(string interopMember) =>
            throw new MutatingCallError(interopMember, $"{interopMember} refused by the test guard.");
    }

    // ---- material_configuration ----------------------------------------------------

    [Fact]
    public void MaterialConfiguration_ForAPart_IsTheConfigurationTheReadWasAttemptedIn()
    {
        Assert.Equal("Machined", PropertyDumper.MaterialConfiguration(DocumentKind.Part, "Machined"));
    }

    [Fact]
    public void MaterialConfiguration_ForAPartWithNoMaterial_IsStillRecorded()
    {
        // The material comes back null for an unassigned part, and the configuration is
        // recorded anyway: "no material in configuration Default" and "no material,
        // configuration unknown" are different facts (contracts/ir-additions.md section 1).
        // The helper is not told what the material read gave, which is what makes that so.
        Assert.Equal("Default", PropertyDumper.MaterialConfiguration(DocumentKind.Part, "Default"));
    }

    [Fact]
    public void MaterialConfiguration_ForAPartInTheDocumentLevelConfiguration_IsEmptyNotNull()
    {
        Assert.Equal(string.Empty, PropertyDumper.MaterialConfiguration(DocumentKind.Part, string.Empty));
    }

    [Theory]
    [InlineData(DocumentKind.Assembly)]
    [InlineData(DocumentKind.Drawing)]
    public void MaterialConfiguration_ForAnAssemblyOrADrawing_IsNullAndOmitted(DocumentKind kind)
    {
        Assert.Null(PropertyDumper.MaterialConfiguration(kind, "Default"));
    }

    [Fact]
    public void MaterialConfiguration_CostsNoInteropCall()
    {
        PropertyDumper.MaterialConfiguration(DocumentKind.Part, "Default");

        // The configuration is already in hand: ReadMaterial passes it to
        // GetMaterialPropertyName2 and discards it today (research R3.2).
        Assert.Empty(_observer.Members);
    }

    // ---- the four fields land on the document --------------------------------------

    [Fact]
    public void TheFourFields_AreOmittedWhenNull()
    {
        // The additivity rule, point 3: a document carrying none of this feature's evidence
        // serializes exactly as it did before 1.4.0. IrSerializerTests measures that over a
        // whole package; here it is the four members' own default.
        var document = new Document();

        Assert.Null(document.IsExploded);
        Assert.Null(document.RebuildErrorCount);
        Assert.Null(document.MassOverridden);
        Assert.Null(document.MaterialConfiguration);
    }
}
