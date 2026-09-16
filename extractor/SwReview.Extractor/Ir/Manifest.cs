using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;
using SwReview.Extractor.Dump;

namespace SwReview.Extractor.Ir;

/// <summary>EvidencePackage.extractor: which tool produced this package.</summary>
public sealed class ExtractorInfo
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("version")]
    public string Version { get; set; } = string.Empty;

    /// <summary>e.g. "2024 SP5"; null for exported-file-only packages.</summary>
    [JsonPropertyName("sw_version")]
    public string? SwVersion { get; set; }

    [JsonPropertyName("machine")]
    public string Machine { get; set; } = string.Empty;

    /// <summary>
    /// Which dump profile wrote this package (schema 1.2.0). Optional in the contract and
    /// defaulted to <see cref="DumpProfile.Full"/>, because every 1.0.0 and 1.1.0 package
    /// predates the member and was a full dump. The vocabulary belongs to the dump command
    /// (Dump/DumpContracts.cs); this DTO only records which one ran.
    /// </summary>
    [JsonPropertyName("profile")]
    public DumpProfile Profile { get; set; } = DumpProfile.Full;
}

/// <summary>contracts/ir.schema.json #/$defs/ManifestEntry. One per document.</summary>
public sealed class ManifestEntry
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("vault_path")]
    public string VaultPath { get; set; } = string.Empty;

    [JsonPropertyName("vault_version")]
    public int? VaultVersion { get; set; }

    [JsonPropertyName("revision")]
    public string? Revision { get; set; }

    [JsonPropertyName("configuration")]
    public string Configuration { get; set; } = string.Empty;

    [JsonPropertyName("local_modified")]
    public bool? LocalModified { get; set; }

    [JsonPropertyName("export_method")]
    public ExportMethod ExportMethod { get; set; } = ExportMethod.Native;

    /// <summary>
    /// <c>FileInfo.LastWriteTimeUtc</c> of <see cref="VaultPath"/> when the dump ran (schema
    /// 1.3.0), truncated to the microsecond the IR carries. Null plus a gap when the path
    /// could not be stat'ed; never 0 and never "now", because the package-reuse key treats an
    /// unknown as a refusal rather than as a match (data-model.md 9.1).
    /// </summary>
    [JsonPropertyName("file_modified_utc")]
    public DateTimeOffset? FileModifiedUtc { get; set; }

    /// <summary><c>FileInfo.Length</c> of the same path, same null-with-a-gap rule.</summary>
    [JsonPropertyName("file_size_bytes")]
    public long? FileSizeBytes { get; set; }
}

/// <summary>contracts/ir.schema.json #/$defs/Discrepancy.</summary>
public sealed class Discrepancy
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("kind")]
    public DiscrepancyKind Kind { get; set; } = DiscrepancyKind.VersionMismatch;

    /// <summary>Schema allows string, integer or null; carried as a JSON-shaped value.</summary>
    [JsonPropertyName("expected")]
    public object? Expected { get; set; }

    [JsonPropertyName("actual")]
    public object? Actual { get; set; }

    [JsonPropertyName("note")]
    public string Note { get; set; } = string.Empty;
}

/// <summary>EvidencePackage.manifest: provenance for every document (FR-002).</summary>
public sealed class Manifest
{
    [JsonPropertyName("entries")]
    public List<ManifestEntry> Entries { get; set; } = new List<ManifestEntry>();

    [JsonPropertyName("discrepancies")]
    public List<Discrepancy> Discrepancies { get; set; } = new List<Discrepancy>();
}

/// <summary>EvidencePackage.design: the design under review, the unit of time measurement.</summary>
public sealed class Design
{
    [JsonPropertyName("design_id")]
    public string DesignId { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("root_assembly_document_id")]
    public string RootAssemblyDocumentId { get; set; } = string.Empty;

    [JsonPropertyName("active_configuration")]
    public string ActiveConfiguration { get; set; } = string.Empty;

    [JsonPropertyName("drawing_document_ids")]
    public List<string> DrawingDocumentIds { get; set; } = new List<string>();
}
