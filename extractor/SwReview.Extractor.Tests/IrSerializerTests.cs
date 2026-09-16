using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using Json.Schema;
using SwReview.Extractor.Ir;
using Xunit;
// SwReview.Extractor.Interference is a namespace (T069), so the IR type is named explicitly.
using IrInterference = SwReview.Extractor.Ir.Interference;

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

        IrInterference interference = Assert.Single(restored.Interferences);
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
    public void SamplePackage_RoundTripsTheSchema110Members()
    {
        // T006. The feature tree, the equations, the suppress-test run and the component's
        // raw constrained status are what the RMS checks read; a member that survives
        // serialization in one direction only is a silently empty check.
        EvidencePackage original = BuildSamplePackage();

        EvidencePackage restored = PackageSerializer.Deserialize(PackageSerializer.Serialize(original));

        Assert.Equal("1.1.0", restored.SchemaVersion);
        Assert.Equal(EvidencePackage.CurrentSchemaVersion, restored.SchemaVersion);

        Assert.Equal(6, restored.Features.Count);
        Assert.Equal(
            new[] { "feat:0001", "feat:0002", "feat:0003", "feat:0004", "feat:0005", "feat:0006" },
            restored.Features.Select(f => f.Id));
        Assert.Equal(new[] { 0, 1, 2, 3, 4, 5 }, restored.Features.Select(f => f.Index));
        Assert.Equal(new[] { 0, 0, 0, 1, 1, 0 }, restored.Features.Select(f => f.Depth));
        Assert.Equal(
            new string?[] { null, null, null, "feat:0003", "feat:0003", null },
            restored.Features.Select(f => f.FolderId));

        Feature sketch = restored.Features[0];
        Assert.Equal("doc:housing", sketch.DocumentId);
        Assert.Equal("Default", sketch.Configuration);
        Assert.Equal("Sketch1", sketch.Name);
        Assert.Equal("ProfileFeature", sketch.TypeName);
        Assert.Equal("outer profile of the boss", sketch.Description);
        Assert.False(sketch.Suppressed);
        Assert.Equal(0, sketch.ErrorCode);
        Assert.Equal(new[] { "feat:0002" }, sketch.ChildIds);
        Assert.Empty(sketch.ParentIds!);
        Assert.NotNull(sketch.Sketch);
        Assert.Equal(3, sketch.Sketch!.RawStatus);
        Assert.Equal(new[] { "feat:0002" }, sketch.Sketch.ConsumerIds);
        Assert.Null(sketch.Fillet);

        // A folder is a feature like any other here: the extractor classifies nothing.
        Feature folder = restored.Features[2];
        Assert.Equal("FtrFolder", folder.TypeName);
        Assert.Equal(string.Empty, folder.Description);
        Assert.Null(folder.Sketch);
        Assert.Null(folder.Fillet);

        Feature fillet = restored.Features[3];
        Assert.True(fillet.Suppressed);
        Assert.NotNull(fillet.Fillet);
        Assert.Equal(0.003, fillet.Fillet!.DefaultRadius!.Value);
        Assert.Equal(LengthUnit.M, fillet.Fillet.DefaultRadius.Unit);

        // Principle I: unknown stays unknown. A variable fillet has no single radius, and a
        // read that failed is null, never a default the reader cannot tell from a value.
        Feature variableFillet = restored.Features[4];
        Assert.Null(variableFillet.Description);
        Assert.Null(variableFillet.Suppressed);
        Assert.Null(variableFillet.ErrorCode);
        Assert.Null(variableFillet.ChildIds);
        Assert.Null(variableFillet.ParentIds);
        Assert.NotNull(variableFillet.Fillet);
        Assert.Null(variableFillet.Fillet!.DefaultRadius);

        Feature unreadSketch = restored.Features[5];
        Assert.NotNull(unreadSketch.Sketch);
        Assert.Null(unreadSketch.Sketch!.RawStatus);
        Assert.Null(unreadSketch.Sketch.ConsumerIds);

        Assert.Equal(2, restored.Equations.Count);
        Assert.Equal("doc:housing", restored.Equations[0].DocumentId);
        Assert.Equal(0, restored.Equations[0].Index);
        Assert.Equal("\"WallThickness\" = 3", restored.Equations[0].Text);
        Assert.Equal("WallThickness", restored.Equations[0].Lhs);
        Assert.True(restored.Equations[0].IsGlobal);
        Assert.Equal(3.0, restored.Equations[0].Value);
        Assert.Equal(1, restored.Equations[1].Index);
        Assert.Equal("D1@Sketch1", restored.Equations[1].Lhs);
        Assert.Null(restored.Equations[1].IsGlobal);
        Assert.Null(restored.Equations[1].Value);

        SuppressTestRun run = restored.RmsSuppressTest!;
        Assert.Equal("doc:housing", run.DocumentId);
        Assert.Equal("Default", run.Configuration);
        Assert.Equal("4-Detail", run.Group);
        Assert.Equal(@"C:\work\bracket\rms-suppress-plan.json", run.PlanFile);
        Assert.True(run.Acknowledged);
        Assert.Equal(0, run.BaselineWhatsWrongCount);
        Assert.Equal(20, run.Limit);
        Assert.Equal(120, run.TimeoutSeconds);
        Assert.Equal(2, run.FeaturesPresent);
        Assert.False(run.RestoreVerified);
        Assert.Equal(new[] { "feat:0005" }, run.UnrestoredFeatureIds);

        Assert.Equal(2, run.Rows.Count);
        Assert.Equal("feat:0004", run.Rows[0].FeatureId);
        Assert.Equal("doc:housing", run.Rows[0].PersistRefScope);
        Assert.Equal("Fillet1", run.Rows[0].Name);
        Assert.Equal(SuppressTestOutcome.Ok, run.Rows[0].Outcome);
        Assert.Equal(0, run.Rows[0].WhatsWrongCount);
        Assert.Equal(new[] { "Fillet1 rebuilt cleanly" }, run.Rows[0].Messages);
        Assert.Equal(0, run.Rows[0].MessagesTruncated);
        Assert.Null(run.Rows[0].Error);
        Assert.Equal(412, run.Rows[0].ElapsedMs);
        Assert.Equal(SuppressTestOutcome.Aborted, run.Rows[1].Outcome);
        Assert.Null(run.Rows[1].WhatsWrongCount);
        Assert.Equal(3, run.Rows[1].MessagesTruncated);
        Assert.Equal(
            "TimeoutException: the rebuild did not finish inside 120 s", run.Rows[1].Error);
        Assert.Null(run.Rows[1].ElapsedMs);

        Assert.Equal(3, restored.Components[0].ConstrainedStatusRaw);
        Assert.Null(restored.Components[1].ConstrainedStatusRaw);
    }

    [Fact]
    public void SamplePackage_WritesTheSchema110NamesAndKeepsUnknownAsNull()
    {
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        Assert.Contains("\"schema_version\": \"1.1.0\"", json, StringComparison.Ordinal);
        Assert.Contains("\"folder_id\": null", json, StringComparison.Ordinal);
        Assert.Contains("\"raw_status\": null", json, StringComparison.Ordinal);
        Assert.Contains("\"consumer_ids\": null", json, StringComparison.Ordinal);
        Assert.Contains("\"default_radius\": null", json, StringComparison.Ordinal);
        Assert.Contains("\"is_global\": null", json, StringComparison.Ordinal);
        Assert.Contains("\"constrained_status_raw\": null", json, StringComparison.Ordinal);
        Assert.Contains("\"baseline_whats_wrong_count\": 0", json, StringComparison.Ordinal);
        Assert.Contains("\"messages_truncated\": 3", json, StringComparison.Ordinal);
    }

    [Fact]
    public void Serialize_WritesEnumsAsTheSchemaStrings()
    {
        EvidencePackage package = BuildSamplePackage();

        // One row per SuppressTestOutcome. The Python rule dispatches on these six strings -
        // ok passes, rebuild_errors fails, not_applied and aborted are unresolved - so a
        // misspelt one would silently drop a tested feature out of the outcome table.
        package.RmsSuppressTest!.Rows.Clear();
        foreach (SuppressTestOutcome outcome in
            (SuppressTestOutcome[])Enum.GetValues(typeof(SuppressTestOutcome)))
        {
            package.RmsSuppressTest.Rows.Add(new SuppressTestRow
            {
                FeatureId = "feat:0004",
                PersistRef = Convert.ToBase64String(new byte[] { 0x41, 0x42, 0x43 }),
                PersistRefScope = "doc:housing",
                Name = outcome.ToString(),
                Outcome = outcome,
                WhatsWrongCount = null,
            });
        }

        package.RmsSuppressTest.FeaturesPresent = package.RmsSuppressTest.Rows.Count;

        string json = PackageSerializer.Serialize(package);

        foreach (string wire in new[]
        {
            "ok", "rebuild_errors", "already_suppressed", "not_applied", "truncated", "aborted",
        })
        {
            Assert.Contains($"\"outcome\": \"{wire}\"", json, StringComparison.Ordinal);
        }

        Assert.Contains("\"suppression\": \"resolved\"", json, StringComparison.Ordinal);
        Assert.Contains("\"identity_source\": \"custom_property\"", json, StringComparison.Ordinal);
        Assert.Contains("\"hole_type\": \"tapped\"", json, StringComparison.Ordinal);
        Assert.Contains("\"unit\": \"mm3\"", json, StringComparison.Ordinal);
        Assert.Contains("\"export_method\": \"native\"", json, StringComparison.Ordinal);
        Assert.Contains("\"kind\": \"not_extracted\"", json, StringComparison.Ordinal);
    }

    [Fact]
    public void SuppressTestRow_DefaultsToAbortedSoAnUnwrittenRowIsNeverASkip()
    {
        // A row the run never reached is unresolved, not skipped: truncated means "planned
        // and deliberately not attempted", which the rule treats as a skip, and defaulting to
        // it would turn a crashed run into a clean review (data-model section 2).
        Assert.Equal(SuppressTestOutcome.Aborted, new SuppressTestRow().Outcome);
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
    /// <summary>
    /// A package with one of everything. Internal so other tests can start from a package
    /// that already satisfies the contract and check only what they produced (T071).
    /// </summary>
    internal static EvidencePackage BuildSamplePackage()
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

                    // swFullyConstrained; the extractor records the number, Python names it.
                    ConstrainedStatusRaw = 3,
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
                new IrInterference
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

            // Schema 1.1.0. The tree is recorded verbatim: the extractor decides nothing
            // about folders, end tags, groups or classes, so "6-Quarantine" and "FtrFolder"
            // are just a name and a type name here.
            Features =
            {
                NewFeature("feat:0001", "Sketch1", "ProfileFeature", index: 0, depth: 0, folderId: null,
                    description: "outer profile of the boss",
                    childIds: new List<string> { "feat:0002" },
                    parentIds: new List<string>(),
                    sketch: new SketchInfo
                    {
                        RawStatus = 3,
                        ConsumerIds = new List<string> { "feat:0002" },
                    }),
                NewFeature("feat:0002", "Boss-Extrude1", "Extrusion", index: 1, depth: 0, folderId: null,
                    description: "core stock the detail is cut from",
                    childIds: new List<string>(),
                    parentIds: new List<string> { "feat:0001" }),
                NewFeature("feat:0003", "6-Quarantine", "FtrFolder", index: 2, depth: 0, folderId: null,
                    description: string.Empty,
                    childIds: new List<string>(),
                    parentIds: new List<string>()),
                NewFeature("feat:0004", "Fillet1", "Fillet", index: 3, depth: 1, folderId: "feat:0003",
                    description: "cosmetic break on the outer edge",
                    childIds: new List<string>(),
                    parentIds: new List<string> { "feat:0002" },
                    fillet: new FilletInfo { DefaultRadius = new Quantity(0.003, LengthUnit.M) },
                    suppressed: true),

                // A variable fillet has no single default radius, and this feature's state
                // could not be read at all: every unknown stays null (Principle I).
                NewFeature("feat:0005", "VarFillet1", "VarFillet", index: 4, depth: 1, folderId: "feat:0003",
                    description: null,
                    childIds: null,
                    parentIds: null,
                    fillet: new FilletInfo { DefaultRadius = null },
                    suppressed: null,
                    errorCode: null),

                // A sketch whose constrained status and consumers could not be read.
                NewFeature("feat:0006", "Sketch2", "ProfileFeature", index: 5, depth: 0, folderId: null,
                    description: "locating slot",
                    childIds: new List<string>(),
                    parentIds: new List<string>(),
                    sketch: new SketchInfo { RawStatus = null, ConsumerIds = null }),
            },
            Equations =
            {
                new Equation
                {
                    DocumentId = "doc:housing",
                    Index = 0,
                    Text = "\"WallThickness\" = 3",
                    Lhs = "WallThickness",
                    IsGlobal = true,
                    Value = 3.0,
                },
                new Equation
                {
                    DocumentId = "doc:housing",
                    Index = 1,
                    Text = "\"D1@Sketch1\" = \"WallThickness\" * 2",
                    Lhs = "D1@Sketch1",

                    // GlobalVariable(1) threw, so whether this drives a dimension is unknown.
                    IsGlobal = null,
                    Value = null,
                },
            },
            RmsSuppressTest = new SuppressTestRun
            {
                DocumentId = "doc:housing",
                Configuration = "Default",
                Group = "4-Detail",
                PlanFile = @"C:\work\bracket\rms-suppress-plan.json",
                RunAt = new DateTimeOffset(2026, 9, 15, 9, 0, 0, TimeSpan.Zero),
                Acknowledged = true,
                BaselineWhatsWrongCount = 0,
                Limit = 20,
                TimeoutSeconds = 120,
                FeaturesPresent = 2,
                RestoreVerified = false,
                UnrestoredFeatureIds = { "feat:0005" },
                Rows =
                {
                    new SuppressTestRow
                    {
                        FeatureId = "feat:0004",
                        PersistRef = Convert.ToBase64String(new byte[] { 0x41, 0x42, 0x43 }),
                        PersistRefScope = "doc:housing",
                        Name = "Fillet1",
                        Outcome = SuppressTestOutcome.Ok,
                        WhatsWrongCount = 0,
                        Messages = { "Fillet1 rebuilt cleanly" },
                        MessagesTruncated = 0,
                        Error = null,
                        ElapsedMs = 412,
                    },
                    new SuppressTestRow
                    {
                        FeatureId = "feat:0005",
                        PersistRef = Convert.ToBase64String(new byte[] { 0x51, 0x52, 0x53 }),
                        PersistRefScope = "doc:housing",
                        Name = "VarFillet1",
                        Outcome = SuppressTestOutcome.Aborted,
                        WhatsWrongCount = null,
                        Messages = { "the rebuild was still running when the timeout expired" },
                        MessagesTruncated = 3,
                        Error = "TimeoutException: the rebuild did not finish inside 120 s",
                        ElapsedMs = null,
                    },
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

    /// <summary>
    /// One feature row of the sample tree. The defaults are the readable case (present,
    /// unsuppressed, no rebuild error); every "could not be read" member is passed as null
    /// explicitly, so the fixture never hides an unknown behind a default.
    /// </summary>
    private static Feature NewFeature(
        string id,
        string name,
        string typeName,
        int index,
        int depth,
        string? folderId,
        string? description,
        List<string>? childIds,
        List<string>? parentIds,
        SketchInfo? sketch = null,
        FilletInfo? fillet = null,
        bool? suppressed = false,
        int? errorCode = 0) =>
        new Feature
        {
            Id = id,
            PersistRef = Convert.ToBase64String(Encoding.UTF8.GetBytes(id)),
            PersistRefScope = "doc:housing",
            DocumentId = "doc:housing",
            Configuration = "Default",
            Name = name,
            TypeName = typeName,
            Description = description,
            Index = index,
            Depth = depth,
            FolderId = folderId,
            Suppressed = suppressed,
            ErrorCode = errorCode,
            ChildIds = childIds,
            ParentIds = parentIds,
            Sketch = sketch,
            Fillet = fillet,
        };
}
