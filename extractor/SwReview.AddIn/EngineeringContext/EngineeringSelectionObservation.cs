using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SwReview.AddIn.EngineeringContext;

/// <summary>One read of the current selection against a host-owned saved evidence package.</summary>
public interface IEngineeringSelectionCapture
{
    EngineeringSelectionObservation Capture(string runDirectory, string expectedPackageSha256);
}

/// <summary>
/// A saved target prefill, never native freshness or engineering approval. References and
/// local paths are private adapter inputs and deliberately absent from this wire response.
/// </summary>
public sealed class EngineeringSelectionObservation
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = "unresolved";

    [JsonPropertyName("observation_id")]
    public Guid ObservationId { get; set; } = Guid.NewGuid();

    [JsonPropertyName("package_id")]
    public Guid? PackageId { get; set; }

    [JsonPropertyName("package_sha256")]
    public string? PackageSha256 { get; set; }

    [JsonPropertyName("root_document_id")]
    public string? RootDocumentId { get; set; }

    [JsonPropertyName("root_configuration")]
    public string? RootConfiguration { get; set; }

    [JsonPropertyName("kind")]
    public string? Kind { get; set; }

    [JsonPropertyName("entity_id")]
    public string? EntityId { get; set; }

    [JsonPropertyName("component_id")]
    public string? ComponentId { get; set; }

    [JsonPropertyName("document_id")]
    public string? DocumentId { get; set; }

    [JsonPropertyName("configuration")]
    public string? Configuration { get; set; }

    [JsonPropertyName("display_name")]
    public string? DisplayName { get; set; }

    [JsonPropertyName("root_dirty")]
    public bool? RootDirty { get; set; }

    [JsonPropertyName("owner_dirty")]
    public bool? OwnerDirty { get; set; }

    [JsonPropertyName("root_dirty_reliable")]
    public bool RootDirtyReliable { get; set; }

    [JsonPropertyName("owner_dirty_reliable")]
    public bool OwnerDirtyReliable { get; set; }

    [JsonPropertyName("native_calibrated")]
    public bool NativeCalibrated => false;

    [JsonPropertyName("native_model_state")]
    public string NativeModelState => "selection_observation_only";

    [JsonPropertyName("freshness")]
    public string Freshness => "cannot_establish";

    [JsonPropertyName("reason_codes")]
    public IReadOnlyList<string> ReasonCodes { get; set; } = Array.Empty<string>();
}
