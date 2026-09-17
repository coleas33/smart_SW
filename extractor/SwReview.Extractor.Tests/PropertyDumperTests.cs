using System;
using SwReview.Extractor.Dump;
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
