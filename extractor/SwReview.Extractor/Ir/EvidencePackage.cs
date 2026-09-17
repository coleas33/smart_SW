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
    public const string CurrentSchemaVersion = "1.4.0";

    /// <summary>Semver; consumers reject any major other than 1 (FR-016).</summary>
    [JsonPropertyName("schema_version")]
    public string SchemaVersion { get; set; } = CurrentSchemaVersion;

    [JsonPropertyName("package_id")]
    public Guid PackageId { get; set; }

    [JsonPropertyName("created_at")]
    public DateTimeOffset CreatedAt { get; set; }

    /// <summary>
    /// What this package claims to be: the <see cref="Dump.ReuseKey"/> digest over the design
    /// and the dump options it was written from (schema 1.3.0, feature 005 lever 9). Null in a
    /// package written by a build that computes none.
    ///
    /// Declared here, ahead of the bulk of the package, because the reuse lookup finds it with
    /// a bounded head read of the first few KiB: a full package is tens of megabytes and the
    /// read happens on the SOLIDWORKS application thread.
    /// </summary>
    [JsonPropertyName("reuse_key")]
    public string? ReuseKey { get; set; }

    /// <summary>
    /// The run folder this package was copied from, or null when it was freshly dumped
    /// (schema 1.3.0). Reuse is stated, never silent: this member, the pane's status line and
    /// the report header all say it.
    /// </summary>
    [JsonPropertyName("reused_from")]
    public string? ReusedFrom { get; set; }

    /// <summary>When the reuse decision was made - not when the original was dumped.</summary>
    [JsonPropertyName("reused_at")]
    public DateTimeOffset? ReusedAt { get; set; }

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

    /// <summary>
    /// PDF-ingested sheets. Always written, empty included: it has been in the contract since
    /// feature 001 and five shipped golden fixtures carry rows in it, so making it
    /// null-when-empty would move every package on disk.
    /// </summary>
    [JsonPropertyName("drawings")]
    public List<DrawingSheet> Drawings { get; set; } = new List<DrawingSheet>();

    /// <summary>
    /// Natively dumped drawing documents (schema 1.4.0), one per drawing, written by the
    /// <c>drawing</c> phase. Beside <see cref="Drawings"/> rather than inside it: that member
    /// is the PDF ingest's <see cref="DrawingSheet"/>, whose page, parse_status and parser a
    /// native sheet has no honest value for (006 research R9).
    ///
    /// Null rather than empty when the phase ran nothing, and omitted from the JSON, so a
    /// package that ran no drawing phase serializes exactly as it did before 1.4.0.
    /// <c>WhenWritingDefault</c> would not do it - it omits a null List, never an empty one -
    /// so <see cref="OmitEmptyAdditiveArrays"/> resolves the emptiness before serialization.
    /// </summary>
    [JsonPropertyName("drawing_records")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<DrawingRecord>? DrawingRecords { get; set; }

    /// <summary>Part feature trees, in traversal order; empty when --features none.</summary>
    [JsonPropertyName("features")]
    public List<Feature> Features { get; set; } = new List<Feature>();

    [JsonPropertyName("equations")]
    public List<Equation> Equations { get; set; } = new List<Equation>();

    /// <summary>
    /// Cut-list items of the package's part documents (schema 1.4.0), written by the
    /// <c>cutlist</c> phase. Null and omitted when the phase recorded none, for the reason
    /// <see cref="DrawingRecords"/> gives.
    /// </summary>
    [JsonPropertyName("cut_list_items")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<CutListItem>? CutListItems { get; set; }

    /// <summary>
    /// The last suppress-test run appended to this package, or null. A dump overwrites the
    /// package and drops it, exactly as it drops interference results.
    /// </summary>
    [JsonPropertyName("rms_suppress_test")]
    public SuppressTestRun? RmsSuppressTest { get; set; }

    /// <summary>Everything that could not be extracted. Never empty by omission.</summary>
    [JsonPropertyName("gaps")]
    public List<Gap> Gaps { get; set; } = new List<Gap>();

    /// <summary>
    /// Nulls the two schema 1.4.0 arrays when they carry no rows, so they are omitted rather
    /// than written as <c>[]</c> (contracts/ir-additions.md, additivity rule point 3).
    ///
    /// Done here, once, on the way into <see cref="PackageSerializer.Serialize"/>, rather
    /// than in every caller that builds a package: a caller that forgot would write an empty
    /// array that is contract-valid, passes every schema check, and still moves every golden
    /// package on disk. Only these two are touched; every array feature 001 shipped keeps
    /// its <c>[]</c>.
    /// </summary>
    internal void OmitEmptyAdditiveArrays()
    {
        if (DrawingRecords != null && DrawingRecords.Count == 0)
        {
            DrawingRecords = null;
        }

        if (CutListItems != null && CutListItems.Count == 0)
        {
            CutListItems = null;
        }
    }
}
