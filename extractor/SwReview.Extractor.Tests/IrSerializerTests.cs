using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Json.Schema;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using Xunit;
// SwReview.Extractor.Interference is a namespace (T069), so the IR type is named explicitly.
using IrInterference = SwReview.Extractor.Ir.Interference;
// SwReview.Extractor.Measure is a namespace too (the remodel geometry), so the IR union
// type is named explicitly the same way.
using IrMeasure = SwReview.Extractor.Ir.Measure;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T021. The C# DTOs and the Python models share one contract file; this test is the C#
/// half of that agreement (the Python half is T013). If the schema changes, this fails.
/// </summary>
public class IrSerializerTests
{
    /// <summary>A stand-in digest of the right shape; the key itself is ReuseKeyTests.</summary>
    private const string SampleReuseKey =
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

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
    public void SamplePackage_RoundTripsTheSchema130Members()
    {
        // T089. `reuse_key` and the per-document file stat are what lever 9 decides on. A
        // member that survives serialization in one direction only is a package claiming to
        // be something no reader can check it against.
        EvidencePackage original = BuildSamplePackage();
        original.ReuseKey = SampleReuseKey;

        string json = PackageSerializer.Serialize(original);
        EvidencePackage restored = PackageSerializer.Deserialize(json);

        Assert.Equal("1.5.0", restored.SchemaVersion);
        Assert.Equal(SampleReuseKey, restored.ReuseKey);
        Assert.Equal(
            new DateTimeOffset(2026, 9, 10, 8, 30, 0, TimeSpan.Zero),
            restored.Manifest.Entries[0].FileModifiedUtc);
        Assert.Equal(262144, restored.Manifest.Entries[0].FileSizeBytes);

        // The second document was never stat'ed: unknown survives as null, never as 0.
        Assert.Null(restored.Manifest.Entries[1].FileModifiedUtc);
        Assert.Null(restored.Manifest.Entries[1].FileSizeBytes);

        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    [Fact]
    public void ReuseKey_IsWrittenBeforeTheBulkOfThePackage()
    {
        // RunFolders answers "what is this run folder" from the first 8 KiB of package.json,
        // because a full package is tens of megabytes and the read happens on the SOLIDWORKS
        // application thread. The reuse lookup's fallback scan finds `reuse_key` the same
        // way, which only works while it is written near the top of the file.
        EvidencePackage package = BuildSamplePackage();
        package.ReuseKey = SampleReuseKey;

        string json = PackageSerializer.Serialize(package);

        Assert.True(
            json.IndexOf("\"reuse_key\"", StringComparison.Ordinal)
                < json.IndexOf("\"extractor\"", StringComparison.Ordinal),
            "reuse_key must be written before extractor so a bounded head read finds it.");
    }

    [Fact]
    public void PackageWithoutTheSchema130Members_StillLoadsAndStillValidates()
    {
        // Every package written before 1.3.0 predates all three members. They are optional in
        // the contract and optional here, so an older package is read, not rejected.
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        string without = Regex.Replace(
            Regex.Replace(json, "\\s*\"reuse_key\": (\"[^\"]*\"|null),", string.Empty),
            ",\\s*\"file_modified_utc\": (\"[^\"]*\"|null),\\s*\"file_size_bytes\": (\\d+|null)",
            string.Empty);

        Assert.DoesNotContain("\"reuse_key\"", without, StringComparison.Ordinal);
        Assert.DoesNotContain("\"file_modified_utc\"", without, StringComparison.Ordinal);

        EvidencePackage restored = PackageSerializer.Deserialize(without);

        Assert.Null(restored.ReuseKey);
        Assert.Null(restored.Manifest.Entries[0].FileModifiedUtc);
        Assert.Null(restored.Manifest.Entries[0].FileSizeBytes);
        EvaluationResults results = Evaluate(without);
        Assert.True(results.IsValid, DescribeFailures(results, without));
    }

    [Fact]
    public void SamplePackage_RoundTripsTheSchema110Members()
    {
        // T006. The feature tree, the equations, the suppress-test run and the component's
        // raw constrained status are what the RMS checks read; a member that survives
        // serialization in one direction only is a silently empty check.
        EvidencePackage original = BuildSamplePackage();

        EvidencePackage restored = PackageSerializer.Deserialize(PackageSerializer.Serialize(original));

        Assert.Equal("1.5.0", restored.SchemaVersion);
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

        Assert.Contains("\"schema_version\": \"1.5.0\"", json, StringComparison.Ordinal);
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
    public void SamplePackage_DefaultsToTheFullProfile()
    {
        // T065, schema 1.2.0. Every package this extractor has ever written was a full dump;
        // the member is added with that as its default so nothing has to be back-filled.
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        Assert.Contains("\"profile\": \"full\"", json, StringComparison.Ordinal);
        Assert.Equal(DumpProfile.Full, PackageSerializer.Deserialize(json).Extractor.Profile);
    }

    [Fact]
    public void ModelCheckPackage_WritesTheProfileAndValidatesAgainstTheContract()
    {
        // The Model check profile leaves holes[], fasteners[], faces[] and bodies[] empty on
        // purpose; profile is the only thing that tells a reader that from a lost dump.
        EvidencePackage package = BuildSamplePackage();
        package.Extractor.Profile = DumpProfile.ModelCheck;

        string json = PackageSerializer.Serialize(package);

        Assert.Contains("\"profile\": \"model_check\"", json, StringComparison.Ordinal);
        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
        Assert.Equal(
            DumpProfile.ModelCheck, PackageSerializer.Deserialize(json).Extractor.Profile);
    }

    [Fact]
    public void PackageWithoutTheProfileMember_StillLoadsAndStillValidates()
    {
        // 1.0.0 and 1.1.0 packages predate the member. It is optional in the contract and
        // optional here, so an older package is read, not rejected.
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        string without = Regex.Replace(json, ",\\s*\"profile\": \"full\"", string.Empty);

        Assert.DoesNotContain("\"profile\"", without, StringComparison.Ordinal);
        Assert.Equal(DumpProfile.Full, PackageSerializer.Deserialize(without).Extractor.Profile);
        EvaluationResults results = Evaluate(without);
        Assert.True(results.IsValid, DescribeFailures(results, without));
    }

    /// <summary>
    /// Feature 005 T033. The per-phase dump timing travels on the extractor block. It is
    /// optional and additive, so a package written before it existed still reads - and a
    /// phase that never ran carries <c>null</c>, never 0, because 0 is a phase that ran and
    /// cost nothing.
    /// </summary>
    [Fact]
    public void PhaseRows_AreWrittenAsNameElapsedAndStatusAndValidateAgainstTheContract()
    {
        EvidencePackage package = BuildSamplePackage();
        package.Extractor.Phases.Add(
            new DumpPhase { Name = "manifest", ElapsedMs = 7, Status = DumpPhaseStatus.Ok });
        package.Extractor.Phases.Add(
            new DumpPhase { Name = "body", ElapsedMs = null, Status = DumpPhaseStatus.Skipped });

        string json = PackageSerializer.Serialize(package);

        Assert.Contains("\"name\": \"manifest\"", json, StringComparison.Ordinal);
        Assert.Contains("\"elapsed_ms\": 7", json, StringComparison.Ordinal);
        Assert.Contains("\"status\": \"skipped\"", json, StringComparison.Ordinal);
        Assert.Contains("\"elapsed_ms\": null", json, StringComparison.Ordinal);

        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));

        ExtractorInfo restored = PackageSerializer.Deserialize(json).Extractor;
        Assert.Equal(new[] { "manifest", "body" }, restored.Phases.Select(phase => phase.Name));
        Assert.Equal(7, restored.Phases[0].ElapsedMs);
        Assert.Null(restored.Phases[1].ElapsedMs);
        Assert.Equal(DumpPhaseStatus.Skipped, restored.Phases[1].Status);
    }

    [Fact]
    public void PackageWithoutThePhasesMember_StillLoadsAndStillValidates()
    {
        // Every package written before T033 predates the member, and the Python writer
        // leaves it out entirely when nothing was timed. It is optional in the contract and
        // optional here, so such a package is read, not rejected.
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        string without = Regex.Replace(json, ",\\s*\"phases\": \\[\\]", string.Empty);

        Assert.DoesNotContain("\"phases\"", without, StringComparison.Ordinal);
        Assert.Empty(PackageSerializer.Deserialize(without).Extractor.Phases);
        EvaluationResults results = Evaluate(without);
        Assert.True(results.IsValid, DescribeFailures(results, without));
    }

    [Fact]
    public void UnknownPhaseStatus_IsRejectedByTheReaderAndByTheContract()
    {
        EvidencePackage package = BuildSamplePackage();
        package.Extractor.Phases.Add(
            new DumpPhase { Name = "mate", ElapsedMs = 3, Status = DumpPhaseStatus.Aborted });

        string json = PackageSerializer.Serialize(package)
            .Replace("\"status\": \"aborted\"", "\"status\": \"gave_up\"");

        Assert.Throws<JsonException>(() => PackageSerializer.Deserialize(json));
        Assert.False(Evaluate(json).IsValid);
    }

    [Fact]
    public void UnknownProfile_IsRejectedByTheReaderAndByTheContract()
    {
        string json = PackageSerializer.Serialize(BuildSamplePackage())
            .Replace("\"profile\": \"full\"", "\"profile\": \"quick\"");

        Assert.Throws<JsonException>(() => PackageSerializer.Deserialize(json));
        Assert.False(Evaluate(json).IsValid);
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

    // ---- schema 1.4.0: the standards evidence (T014) ------------------------------

    /// <summary>
    /// Every addition contracts/ir-additions.md makes, in one package: the ten section 1
    /// fields, the PDF ingest's new <c>source</c> stamp, the widened profile, two
    /// <see cref="CutListItem"/> rows and one <see cref="DrawingRecord"/> carrying one of
    /// each of the seven drawing models. If a DTO and the regenerated contract disagree
    /// about any member name, type or nullability, this is where it shows.
    /// </summary>
    [Fact]
    public void StandardsPackage_SerializesToJsonThatValidatesAgainstTheContract()
    {
        string json = PackageSerializer.Serialize(BuildStandardsPackage());

        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    [Fact]
    public void StandardsPackage_RoundTripsTheSchema140Members()
    {
        // A member that survives serialization in one direction only is evidence the reader
        // silently does not have: every one of these answers a standards check, and a null
        // that arrived by losing the value reads exactly like a null the dump recorded.
        EvidencePackage restored =
            PackageSerializer.Deserialize(PackageSerializer.Serialize(BuildStandardsPackage()));

        Assert.Equal("1.5.0", restored.SchemaVersion);
        Assert.Equal(DumpProfile.Standards, restored.Extractor.Profile);

        Document assembly = restored.Documents[0];
        Assert.True(assembly.IsExploded);
        Assert.Equal(2, assembly.RebuildErrorCount);
        Assert.Null(assembly.MassOverridden);
        Assert.Null(assembly.MaterialConfiguration);

        Document part = restored.Documents[1];
        Assert.Null(part.IsExploded);
        Assert.Equal(0, part.RebuildErrorCount);
        Assert.True(part.MassOverridden);
        Assert.Equal("Default", part.MaterialConfiguration);

        ComponentInstance housing = restored.Components[0];
        Assert.Equal(0.75, housing.TransparencyRaw);
        Assert.True(housing.HasAppearanceOverride);
        Assert.Equal(1, housing.VisibilityRaw);
        Assert.False(housing.IsPatternInstance);

        // The second component was never read: unknown stays unknown on every member.
        ComponentInstance screw = restored.Components[1];
        Assert.Null(screw.TransparencyRaw);
        Assert.Null(screw.HasAppearanceOverride);
        Assert.Null(screw.VisibilityRaw);
        Assert.Null(screw.IsPatternInstance);

        Assert.Equal(
            new MateEntityResolution?[]
            {
                MateEntityResolution.Resolved,
                MateEntityResolution.Unresolved,
                MateEntityResolution.Unknown,
            },
            Assert.Single(restored.Mates).Entities.Select(entity => entity.ResolutionStatus));

        Assert.Equal(0, restored.Features[0].Sketch!.TextSegmentCount);
        Assert.Null(restored.Features[5].Sketch!.TextSegmentCount);

        Assert.Equal(DrawingEvidenceSource.PdfIngest, Assert.Single(restored.Drawings).Source);
    }

    [Fact]
    public void StandardsPackage_RoundTripsTheCutListItems()
    {
        EvidencePackage restored =
            PackageSerializer.Deserialize(PackageSerializer.Serialize(BuildStandardsPackage()));

        Assert.NotNull(restored.CutListItems);
        Assert.Equal(new[] { "cut:0001", "cut:0002" }, restored.CutListItems!.Select(i => i.Id));

        CutListItem first = restored.CutListItems[0];
        Assert.Equal("doc:housing", first.DocumentId);
        Assert.Equal("Default", first.Configuration);
        Assert.Equal("Cut-List-Item1", first.Name);
        Assert.Equal("Cut list", first.FolderName);
        Assert.Equal("CutListFolder", first.FolderTypeName);
        Assert.Equal(2, first.BodyCount);
        Assert.False(first.ExcludedFromCutList);
        Assert.NotEmpty(Convert.FromBase64String(first.PersistRef!));
        Assert.Equal("doc:housing", first.PersistRefScope);

        // The second folder answered neither question, and SOLIDWORKS gave no persistent
        // reference for it: `id` is then the whole identity (FR-026).
        CutListItem second = restored.CutListItems[1];
        Assert.Null(second.BodyCount);
        Assert.Null(second.ExcludedFromCutList);
        Assert.Null(second.PersistRef);
        Assert.Null(second.PersistRefScope);
    }

    [Fact]
    public void StandardsPackage_RoundTripsTheDrawingRecord()
    {
        EvidencePackage restored =
            PackageSerializer.Deserialize(PackageSerializer.Serialize(BuildStandardsPackage()));

        Assert.NotNull(restored.DrawingRecords);
        DrawingRecord drawing = Assert.Single(restored.DrawingRecords!);
        Assert.Equal("doc:drawing", drawing.DocumentId);
        Assert.Equal(DrawingEvidenceSource.Native, drawing.Source);
        Assert.Equal("Sheet1", drawing.ActiveSheetName);
        Assert.Equal(new[] { "dsh:0001", "dsh:0002" }, drawing.Sheets.Select(s => s.Id));

        DrawingSheetRecord active = drawing.Sheets[0];
        Assert.Equal(DrawingEvidenceSource.Native, active.Source);
        Assert.Equal("Sheet1", active.Name);
        Assert.Equal(0, active.Index);
        Assert.Equal("A2-Landscape", active.SheetFormatName);
        Assert.True(active.WasActive);
        Assert.Equal(new[] { "dvw:0001", "dvw:0002" }, active.Views.Select(v => v.Id));

        // The sheet-format pseudo-view: type 1, no referenced model, and the notes live on it.
        DrawingView format = active.Views[0];
        Assert.Equal(1, format.ViewTypeRaw);
        Assert.Null(format.ReferencedDocumentId);
        Assert.Null(format.ReferencedModelPath);
        DrawingNote note = Assert.Single(format.Notes);
        Assert.Equal("dnt:0001", note.Id);
        Assert.Equal("dvw:0001", note.OwnerId);
        Assert.Equal("PLACEHOLDER HANDLING STATEMENT", note.Text);

        DrawingView front = active.Views[1];
        Assert.Equal("Drawing View1", front.Name);
        Assert.Equal("doc:housing", front.ReferencedDocumentId);
        Assert.Equal(SampleModelPath, front.ReferencedModelPath);

        Assert.Equal(
            new[] { "ddm:0001", "ddm:0002", "ddm:0003" },
            front.DisplayDimensions.Select(d => d.Id));
        DisplayDimensionRecord length = front.DisplayDimensions[0];
        Assert.Equal("D1@Sketch1@housing.sldprt", length.Name);
        Assert.True(length.IsOverridden);
        Assert.Equal(12.0, length.OverrideValue!.Value);
        Assert.Equal("mm", length.OverrideValue.Unit);
        Assert.Equal(11.5, length.Value!.Value);

        // An angular dimension: Quantity carries a LengthUnit only, so the Quantity | Angle
        // union is what lets this record exist at all.
        DisplayDimensionRecord angle = front.DisplayDimensions[1];
        Assert.Equal("deg", angle.OverrideValue!.Unit);
        Assert.Equal(30.0, angle.Value!.Value);

        // A number came back and its unit did not, so no number is written: rendering it in
        // a guessed unit is the macro's own bug (difference p).
        DisplayDimensionRecord unitless = front.DisplayDimensions[2];
        Assert.Null(unitless.OverrideValue);
        Assert.Null(unitless.Value);
        Assert.Null(unitless.IsOverridden);

        DrawingAnnotation dangling = Assert.Single(front.Annotations);
        Assert.Equal("dan:0001", dangling.Id);
        Assert.Equal("dvw:0002", dangling.OwnerId);
        Assert.Equal(6, dangling.TypeRaw);
        Assert.True(dangling.IsDangling);

        RevisionTable table = Assert.Single(active.RevisionTables);
        Assert.Equal("drv:0001", table.Id);
        Assert.Equal("dsh:0001", table.SheetId);
        Assert.Equal(string.Empty, table.CurrentRevisionRaw);
        Assert.Equal(2, table.RowCount);
        Assert.Equal(3, table.ColumnCount);
        Assert.Equal(new[] { 0, 1 }, table.Rows.Select(r => r.Index));
        Assert.True(table.Rows[0].IsHeader);
        Assert.Equal(new[] { "REV", "DESCRIPTION", "DATE" }, table.Rows[0].Cells);

        // An empty cell is the empty string; a cell that could not be read is null, and the
        // two must not be confused - an empty revision cell is a real mismatch.
        Assert.Equal(new string?[] { "B", string.Empty, null }, table.Rows[1].Cells);
        Assert.Null(table.Rows[1].IsHeader);

        // Nothing activated the second sheet, and its view enumeration came back empty.
        DrawingSheetRecord quiet = drawing.Sheets[1];
        Assert.False(quiet.WasActive);
        Assert.Null(quiet.SheetFormatName);
        Assert.Empty(quiet.Views);
        Assert.Empty(quiet.RevisionTables);
    }

    /// <summary>
    /// The additivity rule's point 3, on the C# side: every new scalar is omitted when it is
    /// null. <see cref="PackageSerializer"/> is configured
    /// <c>DefaultIgnoreCondition = Never</c> on Principle I grounds, so each of these members
    /// carries the first per-property override of that global, and a missed one writes
    /// <c>"is_exploded": null</c> into every package the extractor has ever produced.
    /// </summary>
    [Fact]
    public void StandardsPackage_OmitsEveryUnreadAdditionRatherThanWritingItsNull()
    {
        string json = PackageSerializer.Serialize(BuildStandardsPackage());

        foreach (string name in new[]
        {
            "is_exploded", "rebuild_error_count", "mass_overridden", "material_configuration",
            "transparency_raw", "has_appearance_override", "visibility_raw",
            "is_pattern_instance", "resolution_status", "text_segment_count", "source",
            "body_count", "excluded_from_cut_list", "active_sheet_name", "sheet_format_name",
            "view_type_raw", "referenced_document_id", "referenced_model_path",
            "dimension_type_raw", "is_overridden", "override_value", "type_raw",
            "is_dangling", "text", "current_revision_raw", "row_count", "column_count",
            "is_header", "persist_ref_scope",
        })
        {
            Assert.DoesNotContain("\"" + name + "\": null", json, StringComparison.Ordinal);
        }
    }

    /// <summary>
    /// The additivity rule's point 5, measured rather than inspected: a package carrying none
    /// of this feature's evidence serializes to exactly the bytes the 1.3.0 build wrote for
    /// it, so the feature 001, 002 and 003 goldens stay byte-identical (SC-004).
    ///
    /// This is the only thing that proves the per-property
    /// <c>[JsonIgnore(WhenWritingNull)]</c> overrides and the null-when-empty arrays work on
    /// the C# side. A stray <c>"cut_list_items": []</c> or <c>"is_exploded": null</c> sails
    /// through every schema validation in this file - both are contract-valid - and still
    /// moves every package on disk.
    ///
    /// The one deliberate difference is the version string itself, and the test states it
    /// rather than letting it hide inside a diff. Newlines are compared normalized: the
    /// baseline is checked in as text and git rewrites its line endings per platform, while
    /// <c>Utf8JsonWriter</c> writes <c>Environment.NewLine</c>.
    /// </summary>
    [Fact]
    public void PackageWithNoneOfTheStandardsEvidence_SerializesToTheBytesThe130BuildWrote()
    {
        // The version string is the current build's: 1.4.0 when this was written, 1.5.0 from
        // feature 010, whose tolerance members are omitted when empty in the same way.
        string baseline = ReadPre140Baseline();
        string expected = baseline.Replace(
            "\"schema_version\": \"1.3.0\"",
            "\"schema_version\": \"" + EvidencePackage.CurrentSchemaVersion + "\"");

        Assert.NotEqual(baseline, expected);

        Assert.Equal(expected, Normalize(PackageSerializer.Serialize(BuildSamplePackage())));
    }

    [Fact]
    public void PackageWithNoneOfTheStandardsEvidence_NamesNoneOfTheNewMembers()
    {
        // The same fact as the byte comparison above, said by name: that one fails on a
        // twelve-kilobyte string and this one fails on the member that moved.
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        foreach (string name in new[]
        {
            "is_exploded", "rebuild_error_count", "mass_overridden", "material_configuration",
            "transparency_raw", "has_appearance_override", "visibility_raw",
            "is_pattern_instance", "text_segment_count", "cut_list_items", "drawing_records",
        })
        {
            Assert.DoesNotContain("\"" + name + "\"", json, StringComparison.Ordinal);
        }
    }

    /// <summary>
    /// A package written before 1.4.0 loads, and every addition comes back as the absence it
    /// was (contracts/ir-additions.md additivity rule point 3, quickstart gate 3). The
    /// baseline fixture IS such a package, so this reads the real thing rather than a 1.4.0
    /// package with members stripped out of its text.
    /// </summary>
    [Fact]
    public void APackageWrittenBefore140_StillLoadsAndStillValidates()
    {
        string json = ReadPre140Baseline();

        EvidencePackage restored = PackageSerializer.Deserialize(json);

        Assert.Equal("1.3.0", restored.SchemaVersion);
        Assert.Null(restored.Documents[0].IsExploded);
        Assert.Null(restored.Documents[0].RebuildErrorCount);
        Assert.Null(restored.Documents[0].MassOverridden);
        Assert.Null(restored.Documents[0].MaterialConfiguration);
        Assert.Null(restored.Components[0].TransparencyRaw);
        Assert.Null(restored.Components[0].HasAppearanceOverride);
        Assert.Null(restored.Components[0].VisibilityRaw);
        Assert.Null(restored.Components[0].IsPatternInstance);
        Assert.Null(restored.Features[0].Sketch!.TextSegmentCount);
        Assert.Null(restored.CutListItems);
        Assert.Null(restored.DrawingRecords);

        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    /// <summary>
    /// A sheet the Python ingest wrote carrying <c>"source"</c> deserializes rather than
    /// throwing. <see cref="PackageSerializer"/> sets
    /// <c>UnmappedMemberHandling.Disallow</c>, and <c>RunPackageIndex</c>,
    /// <c>PackageAppender</c> and <c>PackageReuse</c> all read packages produced elsewhere,
    /// so without the DTO member every ingested package becomes an exception in three places.
    /// </summary>
    [Fact]
    public void SheetWrittenByThePythonIngestCarryingItsSource_Deserializes()
    {
        string json = WithIngestSheet(IngestSheetJson);

        Assert.Contains("\"source\": \"pdf_ingest\"", json, StringComparison.Ordinal);

        DrawingSheet sheet = Assert.Single(PackageSerializer.Deserialize(json).Drawings);

        Assert.Equal(DrawingEvidenceSource.PdfIngest, sheet.Source);
        Assert.Equal("Sheet1", sheet.SheetName);
        Assert.Equal(ParseStatus.Text, sheet.ParseStatus);

        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    [Fact]
    public void SheetWrittenBeforeTheSourceStampExisted_LoadsWithNoSource()
    {
        // Five shipped golden fixtures carry ingested sheets that predate the stamp. Null is
        // "source not recorded", which the drawing checks treat exactly as "pdf_ingest".
        string json = WithIngestSheet(
            IngestSheetJson.Replace(", \"source\": \"pdf_ingest\"", string.Empty));

        Assert.DoesNotContain("\"source\"", json, StringComparison.Ordinal);

        Assert.Null(Assert.Single(PackageSerializer.Deserialize(json).Drawings).Source);
    }

    [Fact]
    public void EnumToJsonName_MatchesTheSchemaSpellingForTheNewEnums()
    {
        Assert.Equal("native", PackageSerializer.EnumToJsonName(DrawingEvidenceSource.Native));
        Assert.Equal(
            "pdf_ingest", PackageSerializer.EnumToJsonName(DrawingEvidenceSource.PdfIngest));
        Assert.Equal("resolved", PackageSerializer.EnumToJsonName(MateEntityResolution.Resolved));
        Assert.Equal(
            "unresolved", PackageSerializer.EnumToJsonName(MateEntityResolution.Unresolved));
        Assert.Equal("unknown", PackageSerializer.EnumToJsonName(MateEntityResolution.Unknown));
        Assert.Equal("standards", PackageSerializer.EnumToJsonName(DumpProfile.Standards));
    }

    [Fact]
    public void StandardsProfile_IsAcceptedByTheReaderAndByTheContract()
    {
        EvidencePackage package = BuildSamplePackage();
        package.Extractor.Profile = DumpProfile.Standards;

        string json = PackageSerializer.Serialize(package);

        Assert.Contains("\"profile\": \"standards\"", json, StringComparison.Ordinal);
        Assert.Equal(
            DumpProfile.Standards, PackageSerializer.Deserialize(json).Extractor.Profile);
        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    /// <summary>
    /// One ingest-written sheet as the Python <c>package_builder</c> writes it from 1.4.0 on.
    /// Authored as text rather than built from the DTO on purpose: what is under test is that
    /// this assembly can read what the other side writes.
    /// </summary>
    private const string IngestSheetJson =
        "{\"document_id\": \"doc:housing\", \"sheet_name\": \"Sheet1\", \"page\": 1, "
        + "\"scale\": \"1:2\", \"units\": \"mm\", \"general_notes\": [], \"dimensions\": [], "
        + "\"views\": [], \"parse_status\": \"text\", \"parser\": \"pdfplumber 0.11.4\""
        + ", \"source\": \"pdf_ingest\"}";

    /// <summary>The sample package with one ingest-written sheet spliced into drawings[].</summary>
    private static string WithIngestSheet(string sheetJson)
    {
        string json = PackageSerializer.Serialize(BuildSamplePackage());
        string written = json.Replace("\"drawings\": [],", "\"drawings\": [" + sheetJson + "],");

        Assert.NotEqual(json, written);
        return written;
    }

    /// <summary>
    /// The bytes the 1.3.0 build wrote for <see cref="BuildSamplePackage"/>, captured from
    /// that build and static thereafter. Newlines normalized, for the reason the byte
    /// comparison above states.
    /// </summary>
    private static string ReadPre140Baseline()
    {
        string path = Path.Combine(AppContext.BaseDirectory, "Fixtures", "package-pre-1.4.0.json");
        Assert.True(
            File.Exists(path),
            "Fixtures/package-pre-1.4.0.json was not copied next to the test assembly; "
            + "check the Content item in the csproj.");
        return Normalize(File.ReadAllText(path));
    }

    private static string Normalize(string text) => text.Replace("\r\n", "\n");

    /// <summary>The referenced model path the sample drawing view names.</summary>
    private const string SampleModelPath = @"C:\work\bracket\housing.sldprt";

    /// <summary>
    /// <see cref="BuildSamplePackage"/> plus every schema 1.4.0 addition: the ten section 1
    /// fields, the ingest's <c>source</c> stamp, the widened profile, two cut-list items and
    /// one drawing record carrying one of each of the seven drawing models.
    ///
    /// Deliberately kept out of <see cref="BuildSamplePackage"/>: that package is what the
    /// byte-identity test measures, and a sample carrying this feature's evidence could not
    /// measure it.
    /// </summary>
    internal static EvidencePackage BuildStandardsPackage()
    {
        EvidencePackage package = BuildSamplePackage();
        package.Extractor.Profile = DumpProfile.Standards;

        // The assembly answers the exploded question and the part never does; nothing read
        // the assembly's mass override, so it stays absent rather than being written false.
        Document assembly = package.Documents[0];
        assembly.IsExploded = true;
        assembly.RebuildErrorCount = 2;

        Document part = package.Documents[1];
        part.RebuildErrorCount = 0;
        part.MassOverridden = true;
        part.MaterialConfiguration = "Default";

        ComponentInstance housing = package.Components[0];
        housing.TransparencyRaw = 0.75;
        housing.HasAppearanceOverride = true;
        housing.VisibilityRaw = 1;
        housing.IsPatternInstance = false;

        package.Mates.Add(new Mate
        {
            Id = "mat:0001",
            PersistRef = Convert.ToBase64String(new byte[] { 0x61, 0x62, 0x63 }),
            PersistRefScope = "doc:asm",
            Type = "CONCENTRIC",
            Alignment = MateAlignment.Aligned,
            Suppressed = false,
            Entities =
            {
                new MateEntityRef
                {
                    ComponentId = "cmp:0001",
                    PersistRef = Convert.ToBase64String(new byte[] { 0x64, 0x65, 0x66 }),
                    EntityKind = "FACE",
                    ResolutionStatus = MateEntityResolution.Resolved,
                },

                // Reference came back null: the mate points at an entity that is gone. Before
                // 1.4.0 this row and the one below were both a null persist_ref and neither
                // could be told from the other, which is the defect the check hunts.
                new MateEntityRef
                {
                    ComponentId = "cmp:0002",
                    PersistRef = null,
                    EntityKind = "FACE",
                    ResolutionStatus = MateEntityResolution.Unresolved,
                },
                new MateEntityRef
                {
                    ComponentId = "cmp:0002",
                    PersistRef = null,
                    EntityKind = "FACE",
                    ResolutionStatus = MateEntityResolution.Unknown,
                },
            },
        });

        // A sketch with no text segments, and one whose text segments could not be read.
        package.Features[0].Sketch!.TextSegmentCount = 0;
        package.Features[5].Sketch!.TextSegmentCount = null;

        package.Drawings.Add(new DrawingSheet
        {
            DocumentId = "doc:housing",
            SheetName = "Sheet1",
            Page = 1,
            Scale = "1:2",
            Units = SheetUnits.Mm,
            ParseStatus = ParseStatus.Text,
            Parser = "pdfplumber 0.11.4",
            Source = DrawingEvidenceSource.PdfIngest,
        });

        package.CutListItems = new List<CutListItem>
        {
            new CutListItem
            {
                Id = "cut:0001",
                DocumentId = "doc:housing",
                Configuration = "Default",
                FolderName = "Cut list",
                FolderTypeName = "CutListFolder",
                Name = "Cut-List-Item1",
                BodyCount = 2,
                ExcludedFromCutList = false,
                PersistRef = Convert.ToBase64String(new byte[] { 0x71, 0x72, 0x73 }),
                PersistRefScope = "doc:housing",
            },

            // Neither question answered and no persistent reference: `id` is the whole
            // identity, and the gaps beside it say which reads failed.
            new CutListItem
            {
                Id = "cut:0002",
                DocumentId = "doc:housing",
                Configuration = "Default",
                FolderName = "Cut list",
                FolderTypeName = "SolidBodyFolder",
                Name = "Cut-List-Item2",
            },
        };

        package.DrawingRecords = new List<DrawingRecord> { NewDrawingRecord() };

        return package;
    }

    /// <summary>
    /// One natively dumped drawing: an active sheet with the sheet-format pseudo-view, a
    /// front view, a revision table and three display dimensions, plus a second sheet nothing
    /// activated and whose view enumeration therefore came back empty.
    /// </summary>
    private static DrawingRecord NewDrawingRecord()
    {
        var format = new DrawingView
        {
            Id = "dvw:0001",
            SheetId = "dsh:0001",
            Name = "Sheet Format1",
            ViewTypeRaw = 1,
            Notes =
            {
                new DrawingNote
                {
                    Id = "dnt:0001",
                    OwnerId = "dvw:0001",
                    Text = "PLACEHOLDER HANDLING STATEMENT",
                },
            },
        };

        var front = new DrawingView
        {
            Id = "dvw:0002",
            SheetId = "dsh:0001",
            Name = "Drawing View1",
            ViewTypeRaw = 2,
            ReferencedDocumentId = "doc:housing",
            ReferencedModelPath = SampleModelPath,
            DisplayDimensions =
            {
                new DisplayDimensionRecord
                {
                    Id = "ddm:0001",
                    ViewId = "dvw:0002",
                    Name = "D1@Sketch1@housing.sldprt",
                    DimensionTypeRaw = 2,
                    IsOverridden = true,
                    OverrideValue = IrMeasure.FromQuantity(new Quantity(12.0, LengthUnit.Mm)),
                    Value = IrMeasure.FromQuantity(new Quantity(11.5, LengthUnit.Mm)),
                },
                new DisplayDimensionRecord
                {
                    Id = "ddm:0002",
                    ViewId = "dvw:0002",
                    Name = "A1@Sketch1@housing.sldprt",
                    DimensionTypeRaw = 3,
                    IsOverridden = false,
                    OverrideValue = IrMeasure.FromAngle(new Angle(30.0, AngleUnit.Deg)),
                    Value = IrMeasure.FromAngle(new Angle(30.0, AngleUnit.Deg)),
                },

                // A number came back and its unit did not, so no number is written.
                new DisplayDimensionRecord
                {
                    Id = "ddm:0003",
                    ViewId = "dvw:0002",
                    Name = "D2@Sketch1@housing.sldprt",
                },
            },
            Annotations =
            {
                new DrawingAnnotation
                {
                    Id = "dan:0001",
                    OwnerId = "dvw:0002",
                    Name = "RevisionSymbol1",
                    TypeRaw = 6,
                    IsDangling = true,
                },
            },
        };

        var table = new RevisionTable
        {
            Id = "drv:0001",
            SheetId = "dsh:0001",

            // Verbatim, including the empty string: the property comes back empty under some
            // vaults and the rows are the other reading, so the check names both with their
            // source rather than letting the dumper choose.
            CurrentRevisionRaw = string.Empty,
            RowCount = 2,
            ColumnCount = 3,
            Rows =
            {
                new RevisionTableRow
                {
                    Index = 0,
                    IsHeader = true,
                    Cells = { "REV", "DESCRIPTION", "DATE" },
                },
                new RevisionTableRow
                {
                    Index = 1,
                    Cells = { "B", string.Empty, null },
                },
            },
        };

        return new DrawingRecord
        {
            DocumentId = "doc:drawing",
            ActiveSheetName = "Sheet1",
            Sheets =
            {
                new DrawingSheetRecord
                {
                    Id = "dsh:0001",
                    Name = "Sheet1",
                    Index = 0,
                    SheetFormatName = "A2-Landscape",
                    WasActive = true,
                    Views = { format, front },
                    RevisionTables = { table },
                },

                // Nothing activates a sheet (FR-044), and this one's view enumeration came
                // back empty: a drawing_sheet_views gap names it and every drawing check is
                // unresolved for that sheet.
                new DrawingSheetRecord
                {
                    Id = "dsh:0002",
                    Name = "Sheet2",
                    Index = 1,
                    WasActive = false,
                },
            },
        };
    }

    // One loader for the whole test assembly (IrContract): JsonSchema.Net registers the
    // schema by its $id in a process-wide registry and the same $id cannot be registered
    // twice.
    private static JsonSchema LoadContractSchema() => IrContract.Load();

    private static EvaluationResults Evaluate(string json)
    {
        using JsonDocument instance = JsonDocument.Parse(json);
        return LoadContractSchema().Evaluate(
            instance.RootElement,
            new EvaluationOptions { OutputFormat = OutputFormat.List });
    }

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
                        FileModifiedUtc = new DateTimeOffset(2026, 9, 10, 8, 30, 0, TimeSpan.Zero),
                        FileSizeBytes = 262144,
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

    // ---- schema 1.5.0: the tolerance evidence (feature 010 T078) ------------------
    //
    // Hole.wizard, EvidencePackage.model_dimensions and model_annotations, with the names
    // the Python models write (specs/010-mechanical-checks/data-model.md section 10). Each is
    // omitted when null or empty, so a package carrying none of it serializes exactly as a
    // 1.4.0 build wrote it apart from the version string (FR-028).

    [Fact]
    public void CurrentSchemaVersion_IsOneFiveZero()
    {
        Assert.Equal("1.5.0", EvidencePackage.CurrentSchemaVersion);
    }

    [Fact]
    public void TolerancePackage_SerializesToJsonThatValidatesAgainstTheContract()
    {
        string json = PackageSerializer.Serialize(BuildTolerancePackage());

        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    [Fact]
    public void TolerancePackage_WritesTheMembersWithThePythonNames()
    {
        // Every optional member set, so each name must appear: no real hole carries all of
        // them at once, and the point here is the spelling, not the combination.
        EvidencePackage package = BuildTolerancePackage();
        package.Holes[0].Wizard!.ThreadClassRaw = "2B";
        package.Holes[0].Wizard!.TapDrillDiameter = new Quantity(0.0042, LengthUnit.M);
        package.Holes[0].Wizard!.CountersinkDiameter = new Quantity(0.0104, LengthUnit.M);
        package.ModelDimensions![0].FitShaftClass = "g6";
        package.ModelAnnotations![0].Frames[0].SymbolXmlRaw = "<GTolFrame/>";
        package.ModelAnnotations[0].DatumIdentifierRaw = "C";

        string json = PackageSerializer.Serialize(package);

        foreach (string name in new[]
        {
            "wizard", "fit_class_raw", "thread_class_raw", "thru_hole_diameter",
            "tap_drill_diameter", "counterbore_diameter", "counterbore_depth",
            "countersink_diameter", "countersink_angle", "head_clearance",
            "model_dimensions", "feature_name", "dimension_type", "dimension_type_raw",
            "nominal", "tolerance_type_raw", "fit_hole_class", "fit_shaft_class",
            "model_annotations", "frames", "number", "symbols_raw", "values_raw",
            "symbol_xml_raw", "datum_identifier_raw", "label", "is_dimxpert",
            "attached_persist_refs",
        })
        {
            Assert.Contains("\"" + name + "\":", json, StringComparison.Ordinal);
        }

        Assert.Contains("\"dimension_type\": \"diameter\"", json, StringComparison.Ordinal);
        Assert.Contains("\"kind\": \"gtol\"", json, StringComparison.Ordinal);
        Assert.Contains("\"kind\": \"datum\"", json, StringComparison.Ordinal);
    }

    [Fact]
    public void TolerancePackage_RoundTripsEveryMember()
    {
        EvidencePackage restored =
            PackageSerializer.Deserialize(PackageSerializer.Serialize(BuildTolerancePackage()));

        HoleWizardData wizard = restored.Holes[0].Wizard!;
        Assert.Equal("swScrewClearanceNormal", wizard.FitClassRaw);
        Assert.Null(wizard.ThreadClassRaw);
        Assert.Equal(0.0066, wizard.ThruHoleDiameter!.Value);
        Assert.Equal(LengthUnit.M, wizard.ThruHoleDiameter.Unit);
        Assert.Equal(0.011, wizard.CounterboreDiameter!.Value);
        Assert.Equal(0.0064, wizard.CounterboreDepth!.Value);
        Assert.Equal(1.5707963267948966, wizard.CountersinkAngle!.Value);
        Assert.Equal(AngleUnit.Rad, wizard.CountersinkAngle.Unit);
        Assert.Equal(0.0005, wizard.HeadClearance!.Value);

        ModelDimension dimension = Assert.Single(restored.ModelDimensions!);
        Assert.Equal("mdm:0001", dimension.Id);
        Assert.Equal("doc:housing", dimension.DocumentId);
        Assert.Equal("Sketch1", dimension.FeatureName);
        Assert.Equal("D1@Sketch1@housing.SLDPRT", dimension.Name);
        Assert.Equal(ModelDimensionType.Diameter, dimension.DimensionType);
        Assert.Equal(6, dimension.DimensionTypeRaw);
        Assert.Equal(0.01, dimension.Nominal.Value);
        Assert.Equal("m", dimension.Nominal.Unit);
        Assert.Equal(ToleranceKind.Bilateral, dimension.Tolerance!.Kind);
        Assert.Equal(0.000015, dimension.Tolerance.Upper!.Value);
        Assert.Equal(0.0, dimension.Tolerance.Lower!.Value);
        Assert.Equal(8, dimension.ToleranceTypeRaw);
        Assert.Equal("H7", dimension.FitHoleClass);
        Assert.Null(dimension.FitShaftClass);

        Assert.Equal(2, restored.ModelAnnotations!.Count);
        ModelAnnotation gtol = restored.ModelAnnotations[0];
        Assert.Equal(ModelAnnotationKind.Gtol, gtol.Kind);
        GtolFrame frame = Assert.Single(gtol.Frames);
        Assert.Equal(1, frame.Number);
        Assert.Equal(new[] { "<GTOL-POSI>", "<MOD-MMC>", "", "", "", "" }, frame.SymbolsRaw);
        Assert.Equal(new[] { "0.05", "", "A", "B", "" }, frame.ValuesRaw);
        Assert.Null(frame.SymbolXmlRaw);
        Assert.False(gtol.IsDimXpert);
        Assert.Single(gtol.AttachedPersistRefs);

        ModelAnnotation datum = restored.ModelAnnotations[1];
        Assert.Equal(ModelAnnotationKind.Datum, datum.Kind);
        Assert.Equal("A", datum.Label);
        Assert.Empty(datum.Frames);
    }

    [Fact]
    public void TolerancePackage_OmitsEveryUnreadMemberRatherThanWritingItsNull()
    {
        EvidencePackage package = BuildTolerancePackage();
        package.Holes[0].Wizard = new HoleWizardData();
        package.ModelDimensions![0].DimensionTypeRaw = null;
        package.ModelDimensions[0].Tolerance = null;
        package.ModelDimensions[0].ToleranceTypeRaw = null;
        package.ModelDimensions[0].FitHoleClass = null;
        package.ModelDimensions[0].PersistRef = null;
        package.ModelDimensions[0].PersistRefScope = null;

        string json = PackageSerializer.Serialize(package);

        // Read, and nothing applied: an empty object, which is not the same fact as a hole
        // whose wizard data was never read.
        Assert.Contains("\"wizard\": {}", json, StringComparison.Ordinal);
        foreach (string name in new[]
        {
            "fit_class_raw", "thread_class_raw", "thru_hole_diameter", "tap_drill_diameter",
            "counterbore_diameter", "counterbore_depth", "countersink_diameter",
            "countersink_angle", "head_clearance", "dimension_type_raw", "tolerance",
            "tolerance_type_raw", "fit_hole_class", "fit_shaft_class",
            "symbol_xml_raw", "datum_identifier_raw", "is_dimxpert",
        })
        {
            Assert.DoesNotContain("\"" + name + "\": null", json, StringComparison.Ordinal);
        }

        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    [Fact]
    public void PackageWithNoneOfTheToleranceEvidence_NamesNoneOfTheNewMembers()
    {
        string json = PackageSerializer.Serialize(BuildSamplePackage());

        foreach (string name in new[] { "wizard", "model_dimensions", "model_annotations" })
        {
            Assert.DoesNotContain("\"" + name + "\"", json, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void EmptyToleranceArrays_AreOmittedLikeTheOtherAdditiveArrays()
    {
        // A caller that assigned an empty list must not write "model_dimensions": [] - it is
        // contract-valid and still moves every package on disk (the 1.4.0 rule, extended).
        EvidencePackage package = BuildSamplePackage();
        package.ModelDimensions = new List<ModelDimension>();
        package.ModelAnnotations = new List<ModelAnnotation>();

        string json = PackageSerializer.Serialize(package);

        Assert.DoesNotContain("\"model_dimensions\"", json, StringComparison.Ordinal);
        Assert.DoesNotContain("\"model_annotations\"", json, StringComparison.Ordinal);
    }

    [Fact]
    public void APackageWrittenAt140_RoundTripsToItsOwnText()
    {
        // A 1.4.0 package re-serialized by this build keeps its version and gains nothing.
        EvidencePackage package = BuildStandardsPackage();
        package.SchemaVersion = "1.4.0";
        string written = PackageSerializer.Serialize(package);

        string again = PackageSerializer.Serialize(PackageSerializer.Deserialize(written));

        Assert.Equal(written, again);
        Assert.Contains("\"schema_version\": \"1.4.0\"", again, StringComparison.Ordinal);
    }

    [Fact]
    public void APackageThePythonModelsWrote_Deserializes()
    {
        // Authored as text, in the shape the Python models serialize: what is under test is
        // that this assembly reads what the other side writes, omitted members included.
        string json = PackageSerializer.Serialize(BuildSamplePackage()).Replace(
            "\"gaps\": [",
            "\"model_dimensions\": [{\"id\": \"mdm:0007\", \"document_id\": \"doc:housing\", "
            + "\"feature_name\": \"Cut-Extrude1\", \"name\": \"D2@Cut-Extrude1@housing.SLDPRT\", "
            + "\"dimension_type\": \"radius\", \"nominal\": {\"value\": 0.002, \"unit\": \"m\"}}], "
            + "\"model_annotations\": [{\"id\": \"man:0003\", \"document_id\": \"doc:housing\", "
            + "\"kind\": \"gtol\", \"frames\": [{\"number\": 2, \"symbol_xml_raw\": \"<f/>\"}]}], "
            + "\"gaps\": [");

        EvidencePackage package = PackageSerializer.Deserialize(json);

        ModelDimension dimension = Assert.Single(package.ModelDimensions!);
        Assert.Equal(ModelDimensionType.Radius, dimension.DimensionType);
        Assert.Null(dimension.Tolerance);
        Assert.Null(dimension.PersistRef);

        GtolFrame frame = Assert.Single(Assert.Single(package.ModelAnnotations!).Frames);
        Assert.Equal(2, frame.Number);
        Assert.Equal("<f/>", frame.SymbolXmlRaw);
        Assert.Empty(frame.SymbolsRaw);

        EvaluationResults results = Evaluate(json);
        Assert.True(results.IsValid, DescribeFailures(results, json));
    }

    [Fact]
    public void AModelDimensionIdOutsideItsPattern_IsRefusedByTheContract()
    {
        EvidencePackage package = BuildTolerancePackage();
        package.ModelDimensions![0].Id = "dim:1";

        EvaluationResults results = Evaluate(PackageSerializer.Serialize(package));

        Assert.False(results.IsValid);
    }

    [Fact]
    public void EnumToJsonName_MatchesTheSchemaSpellingForTheToleranceEnums()
    {
        Assert.Equal("linear", PackageSerializer.EnumToJsonName(ModelDimensionType.Linear));
        Assert.Equal("diameter", PackageSerializer.EnumToJsonName(ModelDimensionType.Diameter));
        Assert.Equal("radius", PackageSerializer.EnumToJsonName(ModelDimensionType.Radius));
        Assert.Equal("angular", PackageSerializer.EnumToJsonName(ModelDimensionType.Angular));
        Assert.Equal("other", PackageSerializer.EnumToJsonName(ModelDimensionType.Other));
        Assert.Equal("gtol", PackageSerializer.EnumToJsonName(ModelAnnotationKind.Gtol));
        Assert.Equal("datum", PackageSerializer.EnumToJsonName(ModelAnnotationKind.Datum));
    }

    /// <summary>
    /// <see cref="BuildSamplePackage"/> plus every schema 1.5.0 addition: wizard data on its
    /// hole, one toleranced diameter dimension and one GTol and one datum tag. Kept out of
    /// <see cref="BuildSamplePackage"/> for the reason <see cref="BuildStandardsPackage"/> is:
    /// that package is what the byte-identity test measures.
    /// </summary>
    internal static EvidencePackage BuildTolerancePackage()
    {
        EvidencePackage package = BuildSamplePackage();
        string dimensionRef = Convert.ToBase64String(new byte[] { 0x41, 0x42, 0x43 });
        string gtolRef = Convert.ToBase64String(new byte[] { 0x51, 0x52, 0x53 });
        string faceRef = Convert.ToBase64String(new byte[] { 0x61, 0x62, 0x63 });

        package.Holes[0].Wizard = new HoleWizardData
        {
            FitClassRaw = "swScrewClearanceNormal",
            ThruHoleDiameter = new Quantity(0.0066, LengthUnit.M),
            CounterboreDiameter = new Quantity(0.011, LengthUnit.M),
            CounterboreDepth = new Quantity(0.0064, LengthUnit.M),
            CountersinkAngle = new Angle(1.5707963267948966, AngleUnit.Rad),
            HeadClearance = new Quantity(0.0005, LengthUnit.M),
        };

        package.ModelDimensions = new List<ModelDimension>
        {
            new ModelDimension
            {
                Id = "mdm:0001",
                DocumentId = "doc:housing",
                FeatureName = "Sketch1",
                Name = "D1@Sketch1@housing.SLDPRT",
                DimensionType = ModelDimensionType.Diameter,
                DimensionTypeRaw = 6,
                Nominal = new IrMeasure(0.01, "m"),
                Tolerance = new Tolerance
                {
                    Kind = ToleranceKind.Bilateral,
                    Upper = new IrMeasure(0.000015, "m"),
                    Lower = new IrMeasure(0.0, "m"),
                    Source = new SourceRef
                    {
                        DocumentId = "doc:housing",
                        Annotation = "D1@Sketch1@housing.SLDPRT",
                        PersistRef = dimensionRef,
                    },
                },
                ToleranceTypeRaw = 8,
                FitHoleClass = "H7",
                PersistRef = dimensionRef,
                PersistRefScope = "doc:housing",
            },
        };

        package.ModelAnnotations = new List<ModelAnnotation>
        {
            new ModelAnnotation
            {
                Id = "man:0001",
                DocumentId = "doc:housing",
                Kind = ModelAnnotationKind.Gtol,
                Frames =
                {
                    new GtolFrame
                    {
                        Number = 1,
                        SymbolsRaw = { "<GTOL-POSI>", "<MOD-MMC>", "", "", "", "" },
                        ValuesRaw = { "0.05", "", "A", "B", "" },
                    },
                },
                IsDimXpert = false,
                AttachedPersistRefs = { faceRef },
                PersistRef = gtolRef,
                PersistRefScope = "doc:housing",
            },
            new ModelAnnotation
            {
                Id = "man:0002",
                DocumentId = "doc:housing",
                Kind = ModelAnnotationKind.Datum,
                DatumIdentifierRaw = null,
                Label = "A",
                AttachedPersistRefs = { faceRef },
            },
        };

        return package;
    }
}
