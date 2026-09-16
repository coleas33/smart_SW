using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// Root of contracts/ir.schema.json: everything extraction writes and every check reads.
/// Property order below follows the schema so a serialized package reads top-down the way
/// the contract does.
/// </summary>
public sealed class EvidencePackage
{
    /// <summary>The schema version this package was written against.</summary>
    public const string CurrentSchemaVersion = "1.2.0";

    /// <summary>Semver; consumers reject any major other than 1 (FR-016).</summary>
    [JsonPropertyName("schema_version")]
    public string SchemaVersion { get; set; } = CurrentSchemaVersion;

    [JsonPropertyName("package_id")]
    public Guid PackageId { get; set; }

    [JsonPropertyName("created_at")]
    public DateTimeOffset CreatedAt { get; set; }

    [JsonPropertyName("extractor")]
    public ExtractorInfo Extractor { get; set; } = new ExtractorInfo();

    [JsonPropertyName("manifest")]
    public Manifest Manifest { get; set; } = new Manifest();

    [JsonPropertyName("design")]
    public Design Design { get; set; } = new Design();

    [JsonPropertyName("documents")]
    public List<Document> Documents { get; set; } = new List<Document>();

    /// <summary>Flat list; the tree is rebuilt from ComponentInstance.parent_id.</summary>
    [JsonPropertyName("components")]
    public List<ComponentInstance> Components { get; set; } = new List<ComponentInstance>();

    [JsonPropertyName("mates")]
    public List<Mate> Mates { get; set; } = new List<Mate>();

    [JsonPropertyName("holes")]
    public List<Hole> Holes { get; set; } = new List<Hole>();

    [JsonPropertyName("threads")]
    public List<CosmeticThread> Threads { get; set; } = new List<CosmeticThread>();

    [JsonPropertyName("fasteners")]
    public List<Fastener> Fasteners { get; set; } = new List<Fastener>();

    /// <summary>Only faces a check needs, unless the dump ran with --faces all.</summary>
    [JsonPropertyName("faces")]
    public List<FaceGeometry> Faces { get; set; } = new List<FaceGeometry>();

    [JsonPropertyName("bodies")]
    public List<BodyRef> Bodies { get; set; } = new List<BodyRef>();

    [JsonPropertyName("interferences")]
    public List<Interference> Interferences { get; set; } = new List<Interference>();

    [JsonPropertyName("captures")]
    public List<Capture> Captures { get; set; } = new List<Capture>();

    [JsonPropertyName("drawings")]
    public List<DrawingSheet> Drawings { get; set; } = new List<DrawingSheet>();

    /// <summary>Part feature trees, in traversal order; empty when --features none.</summary>
    [JsonPropertyName("features")]
    public List<Feature> Features { get; set; } = new List<Feature>();

    [JsonPropertyName("equations")]
    public List<Equation> Equations { get; set; } = new List<Equation>();

    /// <summary>
    /// The last suppress-test run appended to this package, or null. A dump overwrites the
    /// package and drops it, exactly as it drops interference results.
    /// </summary>
    [JsonPropertyName("rms_suppress_test")]
    public SuppressTestRun? RmsSuppressTest { get; set; }

    /// <summary>Everything that could not be extracted. Never empty by omission.</summary>
    [JsonPropertyName("gaps")]
    public List<Gap> Gaps { get; set; } = new List<Gap>();
}
