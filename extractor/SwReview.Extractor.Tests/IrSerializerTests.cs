using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using Json.Schema;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T021. The C# DTOs and the Python models share one contract file; this test is the C#
/// half of that agreement (the Python half is T013). If the schema changes, this fails.
/// </summary>
public class IrSerializerTests
{

    [Fact]
    public void SamplePackage_SerializesToJsonThatValidatesAgainstTheContract()
    {
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        JsonSchema schema = LoadContractSchema();
        using JsonDocument instance = JsonDocument.Parse(json);
        EvaluationResults results = schema.Evaluate(
            instance.RootElement,
            new EvaluationOptions { OutputFormat = OutputFormat.List });

        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    [Fact]
    public void SchemaValidation_RejectsAPackageThatBreaksTheContract()
    {
        // Guards the guard: if the validator were mis-wired, the test above would pass on
        // anything. A component id outside the cmp:NNNN pattern must be caught.
        string json = PackageSerializer.Serialize(BuildSamplePackage())
            .Replace("cmp:0001", "housing-1");

        JsonSchema schema = LoadContractSchema();
        using JsonDocument instance = JsonDocument.Parse(json);
        EvaluationResults results = schema.Evaluate(
            instance.RootElement,
            new EvaluationOptions { OutputFormat = OutputFormat.List });

        Assert.False(results.IsValid);
    }

    [Fact]
    public void SamplePackage_KeepsUnknownThreadDepthAsAnExplicitNull()
    {
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        // Principle I: usable thread depth is unknown, and unknown must survive as null.
        // It is never omitted (the reader could not tell absent from unknown) and never
        // derived from hole_depth.
        Assert.Contains("\"thread_depth\": null", json, StringComparison.Ordinal);
        Assert.Contains("\"hole_depth\": {", json, StringComparison.Ordinal);
    }

    [Fact]
    public void SamplePackage_RoundTripsKeyFields()
    {
        EvidencePackage original = BuildSamplePackage();

        EvidencePackage restored = PackageSerializer.Deserialize(PackageSerializer.Serialize(original));

        Assert.Equal(original.SchemaVersion, restored.SchemaVersion);
        Assert.Equal(original.PackageId, restored.PackageId);
        Assert.Equal(original.CreatedAt, restored.CreatedAt);
        Assert.Equal("2024 SP5", restored.Extractor.SwVersion);

        Assert.Equal(2, restored.Documents.Count);
        Assert.Equal(DocumentKind.Assembly, restored.Documents[0].Kind);
        Assert.Equal(DocumentKind.Part, restored.Documents[1].Kind);
        Assert.Null(restored.Documents[0].Material);
        Assert.Equal("6061-T6", restored.Documents[1].Material);

        Assert.Equal(2, restored.Components.Count);
        for (int i = 0; i < original.Components.Count; i++)
        {
            ComponentInstance expected = original.Components[i];
            ComponentInstance actual = restored.Components[i];

            Assert.Equal(expected.Id, actual.Id);
            Assert.Equal(expected.PersistRef, actual.PersistRef);
            Assert.Equal(expected.PersistRefScope, actual.PersistRefScope);
            Assert.Equal(expected.FullPath, actual.FullPath);
            Assert.Equal(expected.Suppression, actual.Suppression);
            Assert.Equal(expected.ParentId, actual.ParentId);
            Assert.Equal(expected.Transform[3][3], actual.Transform[3][3]);
        }

        // The persist refs survive as decodable base64, never as a mangled string.
        foreach (ComponentInstance component in restored.Components)
        {
            Assert.NotEmpty(Convert.FromBase64String(component.PersistRef));
        }

        Hole hole = Assert.Single(restored.Holes);
        Assert.Equal(HoleType.Tapped, hole.HoleType);
        Assert.Null(hole.ThreadDepth);
        Assert.NotNull(hole.HoleDepth);
        Assert.Equal(12.0, hole.HoleDepth!.Value);
        Assert.Equal(LengthUnit.Mm, hole.HoleDepth.Unit);
        Assert.Equal(EndCondition.Blind, hole.EndCondition);

        Fastener fastener = Assert.Single(restored.Fasteners);
        Assert.Equal(FastenerKind.Screw, fastener.Kind);
        Assert.Equal(IdentitySource.CustomProperty, fastener.IdentitySource);
        Assert.Equal("M6x1.0", fastener.ThreadDesignation);
        Assert.Equal(20.0, fastener.Length!.Value);

        Interference interference = Assert.Single(restored.Interferences);
        Assert.True(interference.IsFastener);
        Assert.True(interference.IsPossible);
        Assert.Equal(InterferenceStatus.Computed, interference.Status);
        Assert.Equal(new[] { "cmp:0001", "cmp:0002" }, interference.ComponentIds);
        Assert.Equal(VolumeUnit.Mm3, interference.Volume!.Unit);
        Assert.Equal(FastenerFolderTreatment.Include, interference.Settings.FastenerFolderTreatment);

        Gap gap = Assert.Single(restored.Gaps);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Equal("hole", gap.EntityKind);
    }

    [Fact]
    public void Serialize_WritesEnumsAsTheSchemaStrings()
    {
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        Assert.Contains("\"suppression\": \"resolved\"", json, StringComparison.Ordinal);
        Assert.Contains("\"identity_source\": \"custom_property\"", json, StringComparison.Ordinal);
        Assert.Contains("\"hole_type\": \"tapped\"", json, StringComparison.Ordinal);
        Assert.Contains("\"unit\": \"mm3\"", json, StringComparison.Ordinal);
        Assert.Contains("\"export_method\": \"native\"", json, StringComparison.Ordinal);
        Assert.Contains("\"kind\": \"not_extracted\"", json, StringComparison.Ordinal);
    }

    [Fact]
    public void EnumToJsonName_MatchesTheSchemaSpelling()
    {
        Assert.Equal("mm", PackageSerializer.EnumToJsonName(LengthUnit.Mm));
        Assert.Equal("in", PackageSerializer.EnumToJsonName(LengthUnit.In));
        Assert.Equal("m", PackageSerializer.EnumToJsonName(LengthUnit.M));
        Assert.Equal("mm3", PackageSerializer.EnumToJsonName(VolumeUnit.Mm3));
        Assert.Equal("deg", PackageSerializer.EnumToJsonName(AngleUnit.Deg));
        Assert.Equal("anti_aligned", PackageSerializer.EnumToJsonName(MateAlignment.AntiAligned));
        Assert.Equal("no_text", PackageSerializer.EnumToJsonName(ParseStatus.NoText));
        Assert.Equal("version_mismatch", PackageSerializer.EnumToJsonName(DiscrepancyKind.VersionMismatch));
    }

    [Fact]
    public void Deserialize_RejectsAnUnknownProperty()
    {
        string json = PackageSerializer.Serialize(BuildSamplePackage())
            .Replace("\"package_id\"", "\"package_identifier\"");

        Assert.ThrowsAny<Exception>(() => PackageSerializer.Deserialize(json));
    }

    // One loader for the whole test assembly (IrContract): JsonSchema.Net registers the
    // schema by its $id in a process-wide registry and the same $id cannot be registered
    // twice.
    private static JsonSchema LoadContractSchema() => IrContract.Load();

    private static string DescribeFailures(EvaluationResults results, string json) =>
        IrContract.DescribeFailures(results, json);

    /// <summary>
    /// A minimal but realistic package: a cover bolted to a housing, one blind tapped hole
    /// whose usable thread depth could not be read, one Toolbox screw, and the fastener
    /// interference SOLIDWORKS reports for the screw in its tapped hole.
    /// </summary>
    private static EvidencePackage BuildSamplePackage()
    {
        string housingRef = Convert.ToBase64String(new byte[] { 0x01, 0x02, 0x03, 0x04, 0x05 });
        string coverRef = Convert.ToBase64String(new byte[] { 0x11, 0x12, 0x13, 0x14, 0x15 });
        string holeRef = Convert.ToBase64String(new byte[] { 0x21, 0x22, 0x23 });
        string screwRef = Convert.ToBase64String(new byte[] { 0x31, 0x32, 0x33 });

        return new EvidencePackage
        {
            SchemaVersion = EvidencePackage.CurrentSchemaVersion,
            PackageId = new Guid("3f2504e0-4f89-11d3-9a0c-0305e82c3301"),
            CreatedAt = new DateTimeOffset(2026, 9, 12, 14, 30, 0, TimeSpan.Zero),
            Extractor = new ExtractorInfo
            {
                Name = "SwReview.Extractor",
                Version = "0.1.0",
                SwVersion = "2024 SP5",
                Machine = "WS-CAD-01",
            },
            Manifest = new Manifest
            {
                Entries =
                {
                    new ManifestEntry
                    {
                        DocumentId = "doc:asm",
                        VaultPath = @"\\vault\projects\bracket\bracket.sldasm",
                        VaultVersion = 7,
                        Revision = "B",
                        Configuration = "Default",
                        LocalModified = false,
                        ExportMethod = ExportMethod.Native,
                    },
                    new ManifestEntry
                    {
                        DocumentId = "doc:housing",
                        VaultPath = @"\\vault\projects\bracket\housing.sldprt",
                        VaultVersion = null,
                        Revision = null,
                        Configuration = "Default",
                        LocalModified = null,
                        ExportMethod = ExportMethod.Native,
                    },
                },
                Discrepancies =
                {
                    new Discrepancy
                    {
                        DocumentId = "doc:housing",
                        Kind = DiscrepancyKind.VersionMismatch,
                        Expected = 7,
                        Actual = 6,
                        Note = "Local copy is one version behind the vault.",
                    },
                },
            },
            Design = new Design
            {
                DesignId = "design:bracket",
                Name = "Bracket assembly",
                RootAssemblyDocumentId = "doc:asm",
                ActiveConfiguration = "Default",
                DrawingDocumentIds = { },
            },
            Documents =
            {
                new Document
                {
                    DocumentId = "doc:asm",
                    Kind = DocumentKind.Assembly,
                    FileName = "bracket.sldasm",
                    Path = @"C:\work\bracket\bracket.sldasm",
                    Configurations = { "Default" },
                    ActiveConfiguration = "Default",
                    CustomProperties = { ["Project"] = "Pilot" },
                    ConfigProperties =
                    {
                        ["Default"] = new Dictionary<string, string> { ["Description"] = "Bracket assembly" },
                    },
                    Material = null,
                    Mass = null,
                },
                new Document
                {
                    DocumentId = "doc:housing",
                    Kind = DocumentKind.Part,
                    FileName = "housing.sldprt",
                    Path = @"C:\work\bracket\housing.sldprt",
                    Configurations = { "Default" },
                    ActiveConfiguration = "Default",
                    CustomProperties = { ["PartNumber"] = "HSG-1001" },
                    ConfigProperties = { },
                    Material = "6061-T6",
                    Mass = new MassProperties
                    {
                        MassKg = 0.412,
                        VolumeM3 = 1.526e-4,
                        CenterOfMass = new Vec3(0.010, 0.020, 0.005),
                        Configuration = "Default",
                    },
                },
            },
            Components =
            {
                new ComponentInstance
                {
                    Id = "cmp:0001",
                    PersistRef = housingRef,
                    PersistRefScope = "doc:asm",
                    Name = "housing-1",
                    FullPath = "housing-1",
                    DocumentId = "doc:housing",
                    ParentId = null,
                    ReferencedConfiguration = "Default",
                    Transform = Transform.Identity(),
                    Suppression = SuppressionState.Resolved,
                    IsFixed = true,
                    PatternId = null,
                    IsToolbox = false,
                },
                new ComponentInstance
                {
                    Id = "cmp:0002",
                    PersistRef = coverRef,
                    PersistRefScope = "doc:asm",
                    Name = "screw-1",
                    FullPath = "housing-1/screw-1",
                    DocumentId = "doc:housing",
                    ParentId = "cmp:0001",
                    ReferencedConfiguration = "M6X1.0X20",
                    Transform = new[]
                    {
                        new[] { 1.0, 0.0, 0.0, 0.012 },
                        new[] { 0.0, 1.0, 0.0, 0.034 },
                        new[] { 0.0, 0.0, 1.0, 0.000 },
                        new[] { 0.0, 0.0, 0.0, 1.0 },
                    },
                    Suppression = SuppressionState.Resolved,
                    IsFixed = false,
                    PatternId = "pat:0001",
                    IsToolbox = true,
                },
            },
            Holes =
            {
                new Hole
                {
                    Id = "hole:0001",
                    PersistRef = holeRef,
                    PersistRefScope = "doc:housing",
                    ComponentId = "cmp:0001",
                    FeatureName = "M6 Tapped Hole1",
                    HoleType = HoleType.Tapped,
                    Standard = "ISO",
                    Size = "M6",
                    ThreadDesignation = "M6x1.0",

                    // The Hole Wizard feature carried a drill depth but no usable thread
                    // depth: it stays null and a Gap says why.
                    ThreadDepth = null,
                    HoleDepth = new Quantity(12.0, LengthUnit.Mm),
                    EndCondition = EndCondition.Blind,
                    Diameter = new Quantity(5.0, LengthUnit.Mm),
                    Axis = new Axis(new Vec3(0.012, 0.034, 0.000), new Vec3(0.0, 0.0, 1.0)),
                    FaceIds = { "face:0001" },
                },
            },
            Fasteners =
            {
                new Fastener
                {
                    Id = "fas:0001",
                    PersistRef = screwRef,
                    PersistRefScope = "doc:asm",
                    ComponentId = "cmp:0002",
                    Kind = FastenerKind.Screw,
                    IdentitySource = IdentitySource.CustomProperty,
                    ThreadDesignation = "M6x1.0",
                    Length = new Quantity(20.0, LengthUnit.Mm),
                    HeadType = "socket head cap",
                    HeadDiameter = new Quantity(10.0, LengthUnit.Mm),
                    HeadHeight = new Quantity(6.0, LengthUnit.Mm),
                    Drive = "hex",
                    Axis = new Axis(new Vec3(0.012, 0.034, 0.010), new Vec3(0.0, 0.0, -1.0)),
                    Material = null,
                },
            },
            Interferences =
            {
                new Interference
                {
                    Id = "int:0001",
                    Configuration = "Default",
                    ComponentIds = { "cmp:0001", "cmp:0002" },
                    Volume = new Volume(41.7, VolumeUnit.Mm3),
                    Settings = new InterferenceSettings
                    {
                        TreatCoincidentAsInterference = false,
                        TreatSubassembliesAsComponents = true,
                        IncludeMultibody = true,
                        IgnoreHidden = false,
                        FastenerFolderTreatment = FastenerFolderTreatment.Include,
                    },
                    IsFastener = true,
                    IsPossible = true,
                    Status = InterferenceStatus.Computed,
                    Error = null,
                    GroupKey = "pat:0001|cmp:0001",
                },
            },
            Gaps =
            {
                new Gap
                {
                    Kind = GapKind.NotExtracted,
                    EntityKind = "hole",
                    EntityId = "hole:0001",
                    Reason = "IWizardHoleFeatureData2.ThreadDepth was not set on this feature.",
                    Error = null,
                },
            },
        };
    }
}
