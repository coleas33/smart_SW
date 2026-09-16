using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.Extractor.Ir;

/// <summary>
/// contracts/ir.schema.json #/$defs/SuppressTestRow (schema 1.1.0). What one planned
/// feature's suppression attempt produced.
/// </summary>
public sealed class SuppressTestRow
{
    [JsonPropertyName("feature_id")]
    public string FeatureId { get; set; } = string.Empty;

    /// <summary>Base64 of GetPersistReference3 bytes.</summary>
    [JsonPropertyName("persist_ref")]
    public string PersistRef { get; set; } = string.Empty;

    /// <summary>document_id whose IModelDocExtension produced persist_ref.</summary>
    [JsonPropertyName("persist_ref_scope")]
    public string PersistRefScope { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("outcome")]
    public SuppressTestOutcome Outcome { get; set; } = SuppressTestOutcome.Truncated;

    /// <summary>GetWhatsWrongCount after the rebuild; null when it was never reached.</summary>
    [JsonPropertyName("whats_wrong_count")]
    public int? WhatsWrongCount { get; set; }

    /// <summary>At most 20 kept.</summary>
    [JsonPropertyName("messages")]
    public List<string> Messages { get; set; } = new List<string>();

    /// <summary>Messages dropped beyond the 20 kept.</summary>
    [JsonPropertyName("messages_truncated")]
    public int MessagesTruncated { get; set; }

    [JsonPropertyName("error")]
    public string? Error { get; set; }

    [JsonPropertyName("elapsed_ms")]
    public int? ElapsedMs { get; set; }
}

/// <summary>
/// contracts/ir.schema.json #/$defs/SuppressTestRun (schema 1.1.0). One
/// <c>suppress-test</c> run appended to the package.
///
/// Written only by the console command through <see cref="Dump.PackageAppender"/>; a later
/// <c>dump</c> overwrites the package and drops it, exactly as interference results are
/// dropped.
/// </summary>
public sealed class SuppressTestRun
{
    [JsonPropertyName("document_id")]
    public string DocumentId { get; set; } = string.Empty;

    [JsonPropertyName("configuration")]
    public string Configuration { get; set; } = string.Empty;

    /// <summary>The Detail group name from the plan.</summary>
    [JsonPropertyName("group")]
    public string Group { get; set; } = string.Empty;

    /// <summary>Path of the plan consumed.</summary>
    [JsonPropertyName("plan_file")]
    public string PlanFile { get; set; } = string.Empty;

    [JsonPropertyName("run_at")]
    public DateTimeOffset RunAt { get; set; }

    /// <summary>Always true; the command refuses otherwise.</summary>
    [JsonPropertyName("acknowledged")]
    public bool Acknowledged { get; set; }

    /// <summary>
    /// Read before the first suppression; the command refuses when non-zero, so this is 0 in
    /// every written run and is recorded for audit.
    /// </summary>
    [JsonPropertyName("baseline_whats_wrong_count")]
    public int BaselineWhatsWrongCount { get; set; }

    /// <summary>--limit in effect.</summary>
    [JsonPropertyName("limit")]
    public int Limit { get; set; }

    /// <summary>--timeout-seconds in effect.</summary>
    [JsonPropertyName("timeout_seconds")]
    public int TimeoutSeconds { get; set; }

    /// <summary>Planned features; equals the number of rows.</summary>
    [JsonPropertyName("features_present")]
    public int FeaturesPresent { get; set; }

    /// <summary>The post-run tree matched the pre-run snapshot.</summary>
    [JsonPropertyName("restore_verified")]
    public bool RestoreVerified { get; set; }

    /// <summary>Empty when <see cref="RestoreVerified"/>.</summary>
    [JsonPropertyName("unrestored_feature_ids")]
    public List<string> UnrestoredFeatureIds { get; set; } = new List<string>();

    /// <summary>One per planned feature, in plan order; untested ones are truncated.</summary>
    [JsonPropertyName("rows")]
    public List<SuppressTestRow> Rows { get; set; } = new List<SuppressTestRow>();
}
